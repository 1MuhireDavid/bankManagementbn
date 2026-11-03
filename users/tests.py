from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from wallets.models import Wallet


class AccountTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'Strong-wallet-password!47',
        }

    def register(self, **overrides):
        return self.client.post('/api/users/register/', self.payload | overrides, format='json')

    def test_registration_hashes_password_and_links_zero_wallet(self):
        response = self.register(is_staff=True, is_superuser=True, balance='1000.00', wallet_id=999)
        self.assertEqual(response.status_code, 201, response.data)
        user = get_user_model().objects.get(username='alice')
        self.assertTrue(user.check_password(self.payload['password']))
        self.assertNotEqual(user.password, self.payload['password'])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(Wallet.objects.filter(owner=user).count(), 1)
        self.assertEqual(response.data['wallet_id'], user.wallet.pk)
        self.assertEqual(response.data['balance'], '0.00')
        self.assertEqual(response.data['email'], 'alice@example.com')
        self.assertNotIn('password', response.data)

    def test_registration_rejects_invalid_fields_and_weak_password(self):
        for overrides in [
            {'username': ''}, {'username': 'invalid username'},
            {'email': ''}, {'email': 'invalid'}, {'password': ''},
            {'password': '12345678'}, {'password': 'short'},
            {'password': 'alice'},
        ]:
            with self.subTest(overrides=overrides):
                self.assertEqual(self.register(**overrides).status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(Wallet.objects.count(), 0)

    def test_missing_fields_and_duplicate_username_rejected(self):
        for field in ['username', 'email', 'password']:
            payload = self.payload.copy()
            del payload[field]
            self.assertEqual(self.client.post('/api/users/register/', payload).status_code, 400)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Wallet.objects.count(), 1)

    def test_signal_handles_shell_and_superuser_creation_without_duplicates(self):
        for user in [
            get_user_model().objects.create_user(username='shell-user'),
            get_user_model().objects.create_superuser(username='admin', password='admin-password'),
        ]:
            self.assertEqual(user.wallet.balance, 0)
            user.email = 'updated@example.com'
            user.save()
            self.assertEqual(Wallet.objects.filter(owner=user).count(), 1)

    def test_failed_wallet_creation_rolls_back_registration(self):
        with patch('users.signals.Wallet.objects.using', side_effect=RuntimeError('wallet storage unavailable')):
            with self.assertRaises(RuntimeError):
                self.register()
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(Wallet.objects.count(), 0)

    def test_login_and_wallet_operations_use_selected_users_token(self):
        self.register()
        other = get_user_model().objects.create_user(username='bob', password='other-password')
        response = self.client.post('/api/users/login/', {
            'username': 'alice', 'password': self.payload['password'],
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {'token'})
        token = response.data['token']
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        self.assertEqual(self.client.get('/api/wallet/').data['balance'], '0.00')
        self.assertEqual(self.client.post('/api/wallet/deposit/', {
            'amount': '10', 'reference': 'registration-deposit', 'wallet_id': other.wallet.pk,
        }).status_code, 200)
        other.wallet.refresh_from_db()
        self.assertEqual(other.wallet.balance, 0)
        self.assertEqual(self.client.get('/api/wallet/').data['balance'], '10.00')
        self.assertEqual(Token.objects.count(), 1)

    def test_login_rejects_wrong_password_inactive_user_and_missing_fields(self):
        self.register()
        for payload in [{}, {'username': 'alice', 'password': 'wrong-password'}]:
            self.assertEqual(self.client.post('/api/users/login/', payload).status_code, 400)
        get_user_model().objects.filter(username='alice').update(is_active=False)
        self.assertEqual(self.client.post('/api/users/login/', {
            'username': 'alice', 'password': self.payload['password'],
        }).status_code, 400)
        self.assertFalse(Token.objects.exists())

    def test_login_reuses_token(self):
        self.register()
        payload = {'username': 'alice', 'password': self.payload['password']}
        first = self.client.post('/api/users/login/', payload)
        second = self.client.post('/api/users/login/', payload)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Token.objects.count(), 1)

    def test_admin_listing_includes_at_least_five_registered_users(self):
        for index in range(5):
            self.assertEqual(self.register(username=f'test-user-{index}', email=f'test-{index}@example.com').status_code, 201)
        admin = get_user_model().objects.create_user(username='staff', is_staff=True)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + Token.objects.create(user=admin).key)
        response = self.client.get('/api/users/wallet-list/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 6)
        self.assertEqual(len(response.data['results']), 6)
        for item in response.data['results']:
            self.assertEqual(set(item), {'id', 'username', 'wallet_id', 'balance'})
            self.assertEqual(item['balance'], '0.00')
        self.assertEqual({r['username'] for r in response.data['results']} - {'staff'}, {f'test-user-{i}' for i in range(5)})

    def test_listing_forbids_anonymous_and_regular_users(self):
        self.assertEqual(self.client.get('/api/users/wallet-list/').status_code, 401)
        user = get_user_model().objects.create_user(username='regular')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + Token.objects.create(user=user).key)
        self.assertEqual(self.client.get('/api/users/wallet-list/').status_code, 403)

    def test_existing_user_migration_backfills_only_missing_wallets(self):
        existing = get_user_model().objects.create_user(username='existing')
        missing = get_user_model().objects.create_user(username='missing')
        Wallet.objects.filter(owner=existing).update(balance='12.00')
        Wallet.objects.filter(owner=missing).delete()
        migration = import_module('wallets.migrations.0003_link_existing_users')
        for _ in range(2):
            migration.link_existing_users(apps, SimpleNamespace(connection=connection))
        self.assertEqual(Wallet.objects.get(owner=existing).balance, 12)
        self.assertEqual(Wallet.objects.get(owner=missing).balance, 0)
        self.assertEqual(Wallet.objects.count(), 2)

    def test_registration_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/api/users/register/', {}).status_code, 400)
        self.assertEqual(self.client.post('/api/users/register/', {}).status_code, 429)
