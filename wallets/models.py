from django.db import models
from django.contrib.auth.models import User
from django.db.models import CheckConstraint, Q

class Wallet(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            CheckConstraint(
                condition=Q(balance__gte=0), 
                name='wallet_balance_gte_0')
        ]


class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (('Credit', 'Credit'), ('Debit', 'Debit'))
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            CheckConstraint(
                condition=Q(amount__gt=0),
                name='wallet_transaction_amount_gt_0'
            )
        ]

