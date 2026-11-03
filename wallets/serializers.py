from decimal import Decimal
from rest_framework import serializers
from .models import Wallet, WalletTransaction


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['balance', 'created_at']
        read_only_fields = fields


class WalletOperationSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(max_length=100, allow_blank=False)


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ['transaction_type', 'amount', 'reference', 'created_at']
        read_only_fields = fields


class WalletOperationResultSerializer(serializers.ModelSerializer):
    new_balance = serializers.DecimalField(source='balance_after', max_digits=10, decimal_places=2)

    class Meta:
        model = WalletTransaction
        fields = ['reference', 'transaction_type', 'amount', 'new_balance']
        read_only_fields = fields
