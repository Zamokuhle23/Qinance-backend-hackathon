from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('loans', '0029_pendingloanapplication')]
    operations = [
        migrations.AddField(model_name='customer', name='business_type', field=models.CharField(blank=True, default='', max_length=100)),
        migrations.AddField(model_name='customer', name='monthly_revenue', field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField(model_name='customer', name='monthly_expenses', field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField(model_name='customer', name='years_operating', field=models.DecimalField(decimal_places=1, default=0, max_digits=5)),
        migrations.AddField(model_name='customer', name='employees_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='loan', name='purpose', field=models.CharField(blank=True, default='', max_length=250)),
    ]

