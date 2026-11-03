from django.conf import settings
from django.db import migrations


def link_existing_users(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Wallet = apps.get_model('wallets', 'Wallet')
    alias = schema_editor.connection.alias
    for user_id in User.objects.using(alias).values_list('pk', flat=True).iterator():
        Wallet.objects.using(alias).get_or_create(owner_id=user_id)


class Migration(migrations.Migration):
    dependencies = [
        ('wallets', '0002_transaction_safety'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(link_existing_users, migrations.RunPython.noop)]
