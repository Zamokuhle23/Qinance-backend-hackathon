from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0023_performance_indexes'),
        ('accounts', '0005_agentprofile_amount_in_hand'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentTransactionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('withdraw', 'Withdraw from Agent'), ('send_to_admin', 'Send Money to Admin')], max_length=20)),
                ('requested_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('actual_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('approved_at', models.DateTimeField(auto_now_add=True)),
                ('note', models.TextField(blank=True, null=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transaction_logs', to='accounts.agentprofile')),
                ('approved_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_agent_transactions', to=settings.AUTH_USER_MODEL)),
                ('transaction_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='log_entry', to='loans.admintransactionrequest')),
            ],
            options={
                'ordering': ['-approved_at'],
            },
        ),
        migrations.AddIndex(
            model_name='agenttransactionlog',
            index=models.Index(fields=['agent', 'approved_at'], name='loans_agent_agent_i_idx'),
        ),
    ]