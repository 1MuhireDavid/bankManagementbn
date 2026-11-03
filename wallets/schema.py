from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

from .serializers import WalletOperationResultSerializer, WalletOperationSerializer


def exclude_legacy_aliases(endpoints):
    """Document canonical routes while keeping older plural routes functional."""
    return [endpoint for endpoint in endpoints if not endpoint[0].startswith('/api/wallets/')]


WALLET_ERRORS = {
    401: OpenApiResponse(description='Missing or invalid API token. Use Authorization: Bearer <your-token>.'),
    404: OpenApiResponse(description='The authenticated user has no wallet.'),
}


def operation_schema(*, withdrawal=False):
    action = 'withdrawal' if withdrawal else 'deposit'
    amount = '2000.00' if withdrawal else '5000.00'
    new_balance = '3000.00' if withdrawal else '5000.00'
    reference = f'demo-{action}-001'
    return extend_schema(
        tags=['Wallet'],
        summary='Withdraw from my wallet' if withdrawal else 'Simulate a deposit into my wallet',
        description=(
            'Only the authenticated user\'s wallet is used. Amount must be positive, with at most '
            'two decimal places and eight integer digits. Reference is required, trimmed and '
            'limited to 100 characters. Balance updates and history are committed together with '
            'a wallet row lock. An exact retry returns the original result, including the original '
            'new_balance; it does not apply the operation again. Reusing a reference with a different '
            'wallet, amount or operation returns 409. '
            + ('Insufficient funds are rejected without changing the wallet.' if withdrawal else
               'This is a simulated deposit. The balance cannot exceed 99999999.99.')
        ),
        request=WalletOperationSerializer,
        responses={
            200: WalletOperationResultSerializer,
            400: OpenApiResponse(description='Invalid amount/reference, insufficient funds or maximum balance exceeded.'),
            409: OpenApiResponse(description='Reference already used for a different wallet, amount or operation.'),
            **WALLET_ERRORS,
        },
        examples=[
            OpenApiExample('Request', value={'amount': amount, 'reference': reference}, request_only=True),
            OpenApiExample('Successful operation or exact retry', value={
                'reference': reference, 'transaction_type': action,
                'amount': amount, 'new_balance': new_balance,
            }, response_only=True, status_codes=['200']),
        ],
    )
