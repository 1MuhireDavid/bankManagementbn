from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.throttling import ScopedRateThrottle

from .serializers import TokenResponseSerializer, UserRegistrationSerializer, UserWalletSerializer


@extend_schema_view(post=extend_schema(
    tags=['Accounts'], summary='Register a user and create their wallet',
    description='Creates a regular Django user and a zero-balance wallet atomically. Passwords are validated and hashed. Log in afterward to obtain an API token.',
    responses={201: UserRegistrationSerializer, 400: OpenApiResponse(description='Invalid input or username already exists.'), 429: OpenApiResponse(description='Registration rate limit exceeded.')},
    examples=[OpenApiExample('Registration', value={
        'username': 'alice', 'email': 'alice@example.com', 'password': 'Choose-a-strong-password!42',
    }, request_only=True)],
))
class UserRegistrationView(CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'registration'


@extend_schema_view(post=extend_schema(
    tags=['Accounts'], summary='Log in and obtain an API token',
    description='Authenticate with username and password. Paste only the returned token into Swagger Authorize; Swagger adds Bearer automatically. Inactive users cannot log in.',
    request=AuthTokenSerializer,
    responses={200: TokenResponseSerializer, 400: OpenApiResponse(description='Missing or invalid credentials.'), 429: OpenApiResponse(description='Login rate limit exceeded.')},
    examples=[OpenApiExample('Login', value={
        'username': 'alice', 'password': 'Choose-a-strong-password!42',
    }, request_only=True)],
))
class UserLoginView(ObtainAuthToken):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class UserWalletPagination(PageNumberPagination):
    page_size = 20


@extend_schema_view(get=extend_schema(
    tags=['Accounts'], summary='List users and wallets (admin only)',
    description='Staff users can inspect user IDs, usernames, wallet IDs and balances. Returns up to 20 existing accounts per page; register at least five users to populate test data. This endpoint never creates users or changes balances. Log in as a listed user to test their wallet operations.',
    responses={200: UserWalletSerializer(many=True), 401: OpenApiResponse(description='Authentication required.'), 403: OpenApiResponse(description='Staff privileges required.')},
))
class UserWalletListView(ListAPIView):
    serializer_class = UserWalletSerializer
    permission_classes = [IsAdminUser]
    pagination_class = UserWalletPagination
    queryset = get_user_model().objects.filter(
        wallet__isnull=False,
    ).select_related('wallet').order_by('id')
