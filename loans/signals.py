# loans/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from accounts.models import AgentProfile
from .models import Customer, Loan, Repayment,CompanyFinance,FinanceTransaction,AdminTransactionRequest,AdminNotification

# ----------------------
# Cache invalidation helpers
# ----------------------
def invalidate_agent_cache(agent_id):
    """Delete cache for agent dashboard and customer list."""
    cache.delete(f"agent_dashboard_{agent_id}")
    cache.delete(f"customer_list_{agent_id}")

def invalidate_admin_cache():
    """Delete cache for admin dashboard (shared across all admins)."""
    cache.delete("admin_dashboard")

def invalidate_admin_finance_cache():
    cache.delete("admin_finance_dashboard")

# ----------------------
# Customer signals
# ----------------------
@receiver(post_save, sender=Customer)
@receiver(post_delete, sender=Customer)
def customer_changed(sender, instance, **kwargs):
    if instance.agent:
        invalidate_agent_cache(instance.agent.id)
    invalidate_admin_cache()  # Admin dashboard also affected



@receiver(post_save, sender=AgentProfile)
@receiver(post_delete, sender=AgentProfile)
def agent_changed(sender, instance, **kwargs):
    # The agent_id is just the PK of this AgentProfile
    invalidate_agent_cache(instance.id)
    invalidate_admin_cache()  # Admin dashboard also affected

# ----------------------
# Loan signals
# ----------------------
@receiver(post_save, sender=Loan)
@receiver(post_delete, sender=Loan)
def loan_changed(sender, instance, **kwargs):
    if instance.customer and instance.customer.agent:
        invalidate_agent_cache(instance.customer.agent.id)
        # Auto-update has_active_loan based on active loans
        customer = instance.customer
        has_active = Loan.objects.filter(customer=customer, status='active').exists()
        if customer.has_active_loan != has_active:
            customer.has_active_loan = has_active
            customer.save(update_fields=['has_active_loan'])
    invalidate_admin_cache()

# ----------------------
# Repayment signals
# ----------------------
@receiver(post_save, sender=Repayment)
@receiver(post_delete, sender=Repayment)
def repayment_changed(sender, instance, **kwargs):
    if instance.loan and instance.loan.customer and instance.loan.customer.agent:
        invalidate_agent_cache(instance.loan.customer.agent.id)
    invalidate_admin_cache()

@receiver(post_save, sender=CompanyFinance)
@receiver(post_delete, sender=CompanyFinance)
@receiver(post_save, sender=FinanceTransaction)
@receiver(post_delete, sender=FinanceTransaction)
@receiver(post_save, sender=AdminTransactionRequest)
@receiver(post_delete, sender=AdminTransactionRequest)
@receiver(post_save, sender=AdminNotification)
@receiver(post_delete, sender=AdminNotification)
def finance_changed(sender, instance, **kwargs):
    invalidate_admin_finance_cache()
    invalidate_admin_cache()  # optional if finance affects main admin dashboard