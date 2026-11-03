from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from wallets.models import Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid='users.create_user_wallet')
def create_user_wallet(sender, instance, created, raw, using, **kwargs):
    """Link every normally-created user to exactly one zero-balance wallet."""
    if created and not raw:
        Wallet.objects.using(using).get_or_create(owner=instance)
