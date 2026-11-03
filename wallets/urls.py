from django.urls import path
from .views import WalletDetailView, WalletDepositView, WalletWithdrawView, TransactionHistoryView

urlpatterns = [
    path('', WalletDetailView.as_view(), name='wallet_detail'),
    path('deposit/', WalletDepositView.as_view(), name='wallet_deposit'),
    path('withdraw/', WalletWithdrawView.as_view(), name='wallet_withdraw'),
    path('transactions/', TransactionHistoryView.as_view(), name='wallet_transactions'),
]