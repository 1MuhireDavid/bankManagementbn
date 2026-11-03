from django.urls import path

from .views import UserLoginView, UserRegistrationView, UserWalletListView

app_name = 'users'

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('wallet-list/', UserWalletListView.as_view(), name='wallet-list'),
]
