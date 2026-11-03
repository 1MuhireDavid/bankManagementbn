from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers


class UserWalletSerializer(serializers.ModelSerializer):
    wallet_id = serializers.IntegerField(source='wallet.id', read_only=True)
    balance = serializers.DecimalField(source='wallet.balance', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = get_user_model()
        fields = ['id', 'username', 'wallet_id', 'balance']
        read_only_fields = fields


class UserRegistrationSerializer(UserWalletSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    email = serializers.EmailField(required=True, allow_blank=False, max_length=254)

    class Meta(UserWalletSerializer.Meta):
        fields = ['id', 'username', 'email', 'password', 'wallet_id', 'balance']
        read_only_fields = ['id', 'wallet_id', 'balance']

    def validate(self, attrs):
        candidate = get_user_model()(username=attrs['username'], email=attrs['email'])
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        User = get_user_model()
        try:
            # The post_save signal runs synchronously. If wallet creation fails,
            # this transaction rolls back the user as well.
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError:
            if User.objects.filter(username=validated_data['username']).exists():
                raise serializers.ValidationError(
                    {'username': 'A user with that username already exists.'}
                ) from None
            raise


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField(read_only=True)
