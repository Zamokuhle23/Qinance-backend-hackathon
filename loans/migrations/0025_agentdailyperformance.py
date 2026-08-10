from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0024_agenttransactionlog'),
        ('accounts', '0005_agentprofile_amount_in_hand'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentDailyPerformance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('gross_interest', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total_withdrawn', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('net', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('loans_collected', models.PositiveIntegerField(default=0)),
                ('total_due_loans', models.PositiveIntegerField(default=0)),
                ('collection_percentage', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_performances', to='accounts.agentprofile')),
            ],
            options={
                'ordering': ['-date'],
            },
        ),
        migrations.AddConstraint(
            model_name='agentdailyperformance',
            constraint=models.UniqueConstraint(fields=['agent', 'date'], name='unique_agent_date_performance'),
        ),
        migrations.AddIndex(
            model_name='agentdailyperformance',
            index=models.Index(fields=['agent', 'date'], name='loans_agent_daily_perf_idx'),
        ),
    ]