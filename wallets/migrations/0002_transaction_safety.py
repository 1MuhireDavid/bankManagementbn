from decimal import Decimal
from uuid import uuid4

from django.db import migrations, models
import django.db.models.deletion


def prepare_history(apps, schema_editor):
    Wallet = apps.get_model('wallets', 'Wallet')
    Transaction = apps.get_model('wallets', 'WalletTransaction')
    alias = schema_editor.connection.alias
    seen = set()
    for wallet in Wallet.objects.using(alias).iterator():
        balance = wallet.balance
        for record in Transaction.objects.using(alias).filter(wallet_id=wallet.pk).order_by('-created_at', '-pk'):
            record.transaction_type = {'Credit': 'deposit', 'Debit': 'withdrawal'}.get(
                record.transaction_type, record.transaction_type,
            )
            reference = (record.reference or '').strip()
            if not reference:
                reference = 'legacy-' + uuid4().hex
            if reference in seen:
                raise RuntimeError('Duplicate transaction references must be resolved before migrating.')
            seen.add(reference)
            record.reference = reference
            record.balance_after = balance
            if balance < Decimal('0.00'):
                raise RuntimeError('Existing transaction history does not match wallet balances.')
            record.save(using=alias, update_fields=['reference', 'transaction_type', 'balance_after'])
            balance += record.amount if record.transaction_type == 'withdrawal' else -record.amount


class Migration(migrations.Migration):
    dependencies = [('wallets', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='wallettransaction', name='balance_after',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True),
        ),
        migrations.RunPython(prepare_history, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='wallet', name='balance',
            field=models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00')),
        ),
        migrations.AlterField(
            model_name='wallettransaction', name='balance_after',
            field=models.DecimalField(max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='wallettransaction', name='reference',
            field=models.CharField(max_length=100, unique=True),
        ),
        migrations.AlterField(
            model_name='wallettransaction', name='transaction_type',
            field=models.CharField(max_length=10, choices=[('deposit', 'Deposit'), ('withdrawal', 'Withdrawal')]),
        ),
        migrations.AlterField(
            model_name='wallettransaction', name='wallet',
            field=models.ForeignKey(to='wallets.wallet', on_delete=django.db.models.deletion.CASCADE, related_name='transactions'),
        ),
        migrations.AlterModelOptions(name='wallettransaction', options={'ordering': ['-created_at', '-pk']}),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.CheckConstraint(condition=~models.Q(reference=''), name='wallet_transaction_reference_nonblank'),
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.CheckConstraint(condition=models.Q(balance_after__gte=0), name='wallet_transaction_balance_gte_0'),
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.CheckConstraint(condition=models.Q(transaction_type__in=['deposit', 'withdrawal']), name='wallet_transaction_type_valid'),
        ),
    ]
