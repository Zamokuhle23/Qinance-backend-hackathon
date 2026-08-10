from django.contrib import admin
from .models import AgentProfile, Customer, Loan, Repayment

admin.site.register(AgentProfile)
admin.site.register(Customer)
admin.site.register(Loan)
admin.site.register(Repayment)
