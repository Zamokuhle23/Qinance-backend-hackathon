from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0022_loan_created_at'),
    ]

    operations = [
        # Loan indexes
        migrations.AddIndex(
            model_name='loan',
            index=models.Index(fields=['status'], name='loans_loan_status_idx'),
        ),
        migrations.AddIndex(
            model_name='loan',
            index=models.Index(fields=['customer', 'status'], name='loans_loan_customer_status_idx'),
        ),
        migrations.AddIndex(
            model_name='loan',
            index=models.Index(fields=['last_paid_date'], name='loans_loan_last_paid_date_idx'),
        ),
        # Repayment indexes
        migrations.AddIndex(
            model_name='repayment',
            index=models.Index(fields=['loan', 'date'], name='loans_repayment_loan_date_idx'),
        ),
        migrations.AddIndex(
            model_name='repayment',
            index=models.Index(fields=['date'], name='loans_repayment_date_idx'),
        ),
        # Customer index
        migrations.AddIndex(
            model_name='customer',
            index=models.Index(fields=['agent'], name='loans_customer_agent_idx'),
        ),
    ]