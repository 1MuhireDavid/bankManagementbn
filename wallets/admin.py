from django.contrib import admin
from .models import Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'balance', 'created_at']
    readonly_fields = ['balance', 'created_at']
    search_fields = ['owner__username']


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ['reference', 'wallet', 'transaction_type', 'amount', 'created_at']
    readonly_fields = ['wallet', 'transaction_type', 'amount', 'reference', 'balance_after', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
