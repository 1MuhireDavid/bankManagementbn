from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name='wallet_balance_gte_0'),
        ]


class WalletTransaction(models.Model):
    class Type(models.TextChoices):
        DEPOSIT = 'deposit', 'Deposit'
        WITHDRAWAL = 'withdrawal', 'Withdrawal'

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=Type.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    # Retain the original result for retries after subsequent transactions.
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='wallet_transaction_amount_gt_0'),
            models.CheckConstraint(condition=~Q(reference=''), name='wallet_transaction_reference_nonblank'),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name='wallet_transaction_balance_gte_0'),
            models.CheckConstraint(
                condition=Q(transaction_type__in=['deposit', 'withdrawal']),
                name='wallet_transaction_type_valid',
            ),
        ]
