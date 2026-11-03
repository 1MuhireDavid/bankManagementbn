from decimal import Decimal
from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError
from .models import Wallet, WalletTransaction


class ReferenceConflict(APIException):
    status_code = 409
    default_detail = 'This reference has already been used for a different request.'
    default_code = 'reference_conflict'


def _check_replay(record, wallet_id, transaction_type, amount):
    if (record.wallet_id, record.transaction_type, record.amount) != (wallet_id, transaction_type, amount):
        raise ReferenceConflict()
    return record


def process_wallet_transaction(*, user, amount, reference, transaction_type):
    """Apply one operation atomically; globally unique references make retries safe."""
    if transaction_type not in WalletTransaction.Type.values:
        raise ValidationError({'transaction_type': 'Invalid transaction type.'})
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise ValidationError({'amount': 'A positive decimal amount is required.'})
    if amount > Decimal('99999999.99') or amount != amount.quantize(Decimal('0.01')):
        raise ValidationError({'amount': 'Use at most eight integer digits and two decimal places.'})
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 100:
        raise ValidationError({'reference': 'A nonblank reference of at most 100 characters is required.'})
    reference = reference.strip()
    wallet_id = None
    try:
        with transaction.atomic():
            try:
                wallet = Wallet.objects.select_for_update().get(owner=user)
            except Wallet.DoesNotExist:
                raise NotFound('Wallet not found.') from None
            wallet_id = wallet.pk
            existing = WalletTransaction.objects.filter(reference=reference).first()
            if existing:
                return _check_replay(existing, wallet_id, transaction_type, amount)
            if transaction_type == WalletTransaction.Type.WITHDRAWAL:
                if wallet.balance < amount:
                    raise ValidationError({'amount': 'Insufficient funds.'})
                new_balance = wallet.balance - amount
            else:
                new_balance = wallet.balance + amount
                if new_balance > Decimal('99999999.99'):
                    raise ValidationError({'amount': 'Deposit exceeds the maximum wallet balance.'})
            wallet.balance = new_balance
            wallet.save(update_fields=['balance'])
            return WalletTransaction.objects.create(
                wallet=wallet, transaction_type=transaction_type, amount=amount,
                reference=reference, balance_after=new_balance,
            )
    except IntegrityError:
        # A different wallet may have claimed this reference concurrently.
        # Inspect the winner only after this transaction has rolled back.
        existing = WalletTransaction.objects.filter(reference=reference).first()
        if existing is None:
            raise
        return _check_replay(existing, wallet_id, transaction_type, amount)
