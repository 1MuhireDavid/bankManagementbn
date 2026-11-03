from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .models import Wallet, WalletTransaction
from .serializers import WalletOperationSerializer
from .services import ReferenceConflict, process_wallet_transaction


class InputValidationTests(TestCase):
    def test_invalid_inputs(self):
        invalid = [
            {}, {'amount': '1.00'}, {'reference': 'ref'},
            {'amount': '0', 'reference': 'ref'},
            {'amount': '-1', 'reference': 'ref'},
            {'amount': '1.001', 'reference': 'ref'},
            {'amount': '1', 'reference': ''},
            {'amount': '1', 'reference': '   '},
            {'amount': '1', 'reference': 'x' * 101},
            {'amount': 'NaN', 'reference': 'ref'},
            {'amount': 'Infinity', 'reference': 'ref'},
            {'amount': 'bad', 'reference': 'ref'},
            {'amount': None, 'reference': 'ref'},
            {'amount': '100000000.00', 'reference': 'ref'},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertFalse(WalletOperationSerializer(data=payload).is_valid())

    def test_decimal_and_reference_normalization(self):
        serializer = WalletOperationSerializer(data={'amount': '0.01', 'reference': ' ref '})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {'amount': Decimal('0.01'), 'reference': 'ref'})


class WalletAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='alice', password='test-password')
        self.other = get_user_model().objects.create_user(username='bob', password='test-password')
        self.wallet = Wallet.objects.get(owner=self.user)
        self.other_wallet = Wallet.objects.get(owner=self.other)
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.token.key)

    def post(self, action, amount, reference, **extra):
        return self.client.post('/api/wallet/' + action + '/', {
            'amount': amount, 'reference': reference, **extra,
        }, format='json')

    def test_unauthenticated_and_invalid_tokens_rejected_everywhere(self):
        for header in [None, 'Bearer invalid-token']:
            self.client.credentials(**({'HTTP_AUTHORIZATION': header} if header else {}))
            for method, path in [('get', ''), ('get', 'transactions/'), ('post', 'deposit/'), ('post', 'withdraw/')]:
                with self.subTest(header=header, path=path):
                    self.assertEqual(getattr(self.client, method)('/api/wallet/' + path).status_code, 401)

    def test_own_zero_balance_and_legacy_alias(self):
        for url in ['/api/wallet/', '/api/wallets/']:
            response = self.client.get(url, {'owner': self.other.pk})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['balance'], '0.00')
            self.assertNotIn('owner', response.data)

    def test_deposit_withdrawal_and_original_replay_result(self):
        deposit = self.post('deposit', '5000', 'deposit-1')
        self.assertEqual(deposit.status_code, 200)
        self.assertEqual(deposit.data['new_balance'], '5000.00')
        self.assertEqual(self.post('deposit', '5000', 'deposit-1').data, deposit.data)
        self.assertEqual(WalletTransaction.objects.count(), 1)
        withdrawal = self.post('withdraw', '2000', 'withdraw-1')
        self.assertEqual(withdrawal.data['new_balance'], '3000.00')
        self.assertEqual(self.post('withdraw', '4000', 'insufficient').status_code, 400)
        self.assertEqual(self.post('withdraw', '2000', 'withdraw-1').data, withdrawal.data)
        self.assertEqual(self.post('deposit', '5000', 'deposit-1').data, deposit.data)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('3000.00'))
        self.assertEqual(WalletTransaction.objects.count(), 2)
        self.assertFalse(WalletTransaction.objects.filter(reference='insufficient').exists())

    def test_conflicting_references(self):
        self.post('deposit', '10', 'shared')
        self.assertEqual(self.post('deposit', '11', 'shared').status_code, 409)
        self.assertEqual(self.post('withdraw', '10', 'shared').status_code, 409)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + Token.objects.create(user=self.other).key)
        self.assertEqual(self.post('deposit', '10', 'shared').status_code, 409)
        self.other_wallet.refresh_from_db()
        self.assertEqual(self.other_wallet.balance, 0)
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_owner_input_cannot_redirect_operation(self):
        self.post('deposit', '10', 'owner-test', owner=self.other.pk, wallet=self.other_wallet.pk)
        self.wallet.refresh_from_db()
        self.other_wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('10.00'))
        self.assertEqual(self.other_wallet.balance, 0)

    def test_invalid_input_changes_nothing(self):
        for action in ['deposit', 'withdraw']:
            for payload in [
                {'amount': '0', 'reference': 'invalid'},
                {'amount': '-10', 'reference': 'invalid'},
                {'amount': '1.001', 'reference': 'invalid'},
                {'amount': '10'}, {'amount': '10', 'reference': ' '},
            ]:
                with self.subTest(action=action, payload=payload):
                    self.assertEqual(self.client.post('/api/wallet/' + action + '/', payload).status_code, 400)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_overflow_is_rejected(self):
        self.post('deposit', '99999999.99', 'maximum')
        self.assertEqual(self.post('deposit', '0.01', 'overflow').status_code, 400)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('99999999.99'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_missing_wallet_is_404(self):
        self.wallet.delete()
        for response in [
            self.client.get('/api/wallet/'), self.client.get('/api/wallet/transactions/'),
            self.post('deposit', '1', 'missing'), self.post('withdraw', '1', 'missing'),
        ]:
            self.assertEqual(response.status_code, 404)

    def test_paginated_history_is_newest_first_and_private(self):
        for i in range(21):
            self.post('deposit', '1', f'history-{i}')
        response = self.client.get('/api/wallet/transactions/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 21)
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['results'][0]['reference'], 'history-20')
        self.assertEqual(set(response.data['results'][0]), {'transaction_type', 'amount', 'reference', 'created_at'})
        second_page = self.client.get('/api/wallet/transactions/?page=2')
        self.assertEqual(second_page.data['results'][0]['reference'], 'history-0')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + Token.objects.create(user=self.other).key)
        self.assertEqual(self.client.get('/api/wallet/transactions/').data['count'], 0)
        self.assertEqual(self.client.get('/api/wallet/').data['balance'], '0.00')

    def test_history_insert_failure_rolls_back_balance(self):
        with patch('wallets.services.WalletTransaction.objects.create', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.post('deposit', '10', 'rollback')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)


class ConstraintTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='constraints')
        self.wallet = Wallet.objects.get(owner=self.user)

    def test_negative_balance_and_duplicate_wallet_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=self.wallet.pk).update(balance=Decimal('-0.01'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(owner=self.user)

    def test_invalid_transaction_values_rejected_by_database(self):
        base = dict(wallet=self.wallet, transaction_type='deposit', amount=Decimal('1'), reference='valid', balance_after=Decimal('1'))
        for override in [
            {'amount': Decimal('0')}, {'amount': Decimal('-1')},
            {'reference': ''}, {'reference': None},
            {'transaction_type': 'invalid'}, {'balance_after': Decimal('-1')},
        ]:
            with self.subTest(override=override):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    WalletTransaction.objects.create(**(base | override))
        WalletTransaction.objects.create(**base)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WalletTransaction.objects.create(**base)


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='concurrent')
        self.other = get_user_model().objects.create_user(username='concurrent-other')
        self.wallet = Wallet.objects.get(owner=self.user)
        Wallet.objects.get(owner=self.other)

    def run_parallel(self, operations):
        barrier = Barrier(len(operations))

        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    result = process_wallet_transaction(**operation)
                    return ('ok', result.reference)
                except ReferenceConflict:
                    return ('conflict', None)
                except Exception as exc:
                    return (type(exc).__name__, str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(worker, operations))

    def operation(self, reference, amount='1.00', user=None, kind='deposit'):
        return dict(user=user or self.user, reference=reference, amount=Decimal(amount), transaction_type=kind)

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_deposits_do_not_lose_updates(self):
        results = self.run_parallel([self.operation('parallel-a'), self.operation('parallel-b')])
        self.assertEqual([r[0] for r in results], ['ok', 'ok'], results)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('2.00'))
        self.assertEqual(WalletTransaction.objects.count(), 2)

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_duplicate_is_applied_once(self):
        results = self.run_parallel([self.operation('same'), self.operation('same')])
        self.assertEqual([r[0] for r in results], ['ok', 'ok'], results)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_global_reference_race_rolls_back_loser(self):
        results = self.run_parallel([self.operation('global'), self.operation('global', user=self.other)])
        self.assertCountEqual([r[0] for r in results], ['ok', 'conflict'], results)
        self.assertEqual(sum(Wallet.objects.values_list('balance', flat=True)), Decimal('1.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_withdrawals_cannot_overdraw(self):
        process_wallet_transaction(**self.operation('fund', amount='10'))
        results = self.run_parallel([
            self.operation('withdraw-a', amount='8', kind='withdrawal'),
            self.operation('withdraw-b', amount='8', kind='withdrawal'),
        ])
        self.assertCountEqual([r[0] for r in results], ['ok', 'ValidationError'], results)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('2.00'))
        self.assertEqual(WalletTransaction.objects.count(), 2)
