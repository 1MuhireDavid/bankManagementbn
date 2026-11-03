from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Wallet, WalletTransaction
from .serializers import (
    WalletOperationResultSerializer, WalletOperationSerializer,
    WalletSerializer, WalletTransactionSerializer,
)
from .services import process_wallet_transaction
from .schema import WALLET_ERRORS, operation_schema


@extend_schema_view(get=extend_schema(
    tags=['Wallet'], summary='View my wallet',
    description='Returns the authenticated user\'s balance and creation time. Owner IDs are never accepted.',
    responses={200: WalletSerializer, **WALLET_ERRORS},
    examples=[OpenApiExample('New wallet', value={
        'balance': '0.00', 'created_at': '2026-11-03T12:00:00Z',
    }, response_only=True)],
))
class WalletDetailView(RetrieveAPIView):
    serializer_class = WalletSerializer
    queryset = Wallet.objects.none()

    def get_object(self):
        return get_object_or_404(Wallet, owner=self.request.user)


class WalletOperationView(APIView):
    transaction_type = None

    def post(self, request):
        serializer = WalletOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = process_wallet_transaction(
            user=request.user, transaction_type=self.transaction_type,
            **serializer.validated_data,
        )
        return Response(WalletOperationResultSerializer(result).data)


@extend_schema_view(post=operation_schema())
class WalletDepositView(WalletOperationView):
    transaction_type = WalletTransaction.Type.DEPOSIT


@extend_schema_view(post=operation_schema(withdrawal=True))
class WalletWithdrawView(WalletOperationView):
    transaction_type = WalletTransaction.Type.WITHDRAWAL


class TransactionPagination(PageNumberPagination):
    page_size = 20


@extend_schema_view(get=extend_schema(
    tags=['Wallet'], summary='Browse my transaction history',
    description='Only your transactions, newest first (creation date then ID). Returns 20 records per page.',
    responses={200: WalletTransactionSerializer(many=True), **WALLET_ERRORS},
))
class TransactionHistoryView(ListAPIView):
    serializer_class = WalletTransactionSerializer
    pagination_class = TransactionPagination

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return WalletTransaction.objects.none()
        wallet = get_object_or_404(Wallet, owner=self.request.user)
        return wallet.transactions.all()
