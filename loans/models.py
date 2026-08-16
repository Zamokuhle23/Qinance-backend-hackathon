from functools import cached_property
from django.db import models
from django.contrib.auth.models import User
from datetime import date, timedelta,timezone
from decimal import Decimal
from accounts.models import AgentProfile
from django.utils.timezone import now
from django.db import OperationalError, ProgrammingError
from datetime import timedelta

class LoanSettings(models.Model):
    interest_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    duration_days = models.PositiveIntegerField(default=20)
    min_loan_amount = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    max_loan_amount = models.DecimalField(max_digits=10, decimal_places=2, default=1000)



class Customer(models.Model):
    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    location = models.CharField(max_length=100, blank=True, null=True)  # <-- new field
    national_id = models.CharField(max_length=20, unique=True)
    created_at = models.DateField(auto_now_add=True)
    credit_score = models.IntegerField(default=1000)  # determines upper limit
    blacklisted = models.BooleanField(default=False)
    has_active_loan = models.BooleanField(default=False)
    business_type = models.CharField(max_length=100, blank=True, default='')
    monthly_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monthly_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    years_operating = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    employees_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['agent']),
        ]

    def __str__(self):
        """Return current qualification range"""
        settings = LoanSettings.objects.first()
        upperSettings = settings.max_loan_amount if settings else 500
        lowerSettings = settings.min_loan_amount if settings else 200

        lower = lowerSettings
        upper = self.credit_score if self.credit_score else upperSettings
        return lower, upper

    def update_credit_score(self, loan):
        """Update score based on performance of the last loan"""
        if loan.status != "completed":
            return

        days_early = (loan.end_date - loan.last_paid_date).days if loan.last_paid_date else 0

        if loan.days_missed == 0 and days_early >= 3:
            # Paid early
            self.credit_score = min(self.credit_score + 250, 2000)
        elif loan.days_missed == 0:
            # Paid on time
            self.credit_score = min(self.credit_score + 200, 2000)
        else:
            # Paid late or missed
            self.credit_score = max(self.credit_score - 100, 200)

        self.save()

def get_holidays():
    """Return a cached set of public holiday dates. Refreshes every hour."""
    from django.core.cache import cache
    holidays = cache.get('public_holidays')
    if holidays is None:
        try:
            from loans.models import PublicHoliday
            holidays = set(PublicHoliday.objects.values_list("holiday_date", flat=True))
        except (OperationalError, ProgrammingError):
            holidays = set()
        cache.set('public_holidays', holidays, timeout=3600)
    return holidays
    

class Loan(models.Model):
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE)
    principal_amount = models.DecimalField(max_digits=10, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    total_due = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    daily_payment = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    duration_days = models.IntegerField(default=20)
    last_payment_at = models.DateTimeField(null=True, blank=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, default='active')
    last_paid_date = models.DateField(null=True, blank=True)
    days_paid = models.IntegerField(default=0)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    display_order = models.IntegerField(default=0, db_index=True)
    purpose = models.CharField(max_length=250, blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['last_paid_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.total_due:
            self.total_due = self.principal_amount + (
                self.principal_amount * self.interest_rate / Decimal(100)
            )
        if not self.daily_payment:
            self.daily_payment = self.total_due / Decimal(self.duration_days)

        if not self.start_date:
            proposed_date = date.today() + timedelta(days=1)
            holidays = get_holidays()
            while proposed_date.weekday() >= 5 or proposed_date in holidays:
                proposed_date += timedelta(days=1)
            self.start_date = proposed_date

        if not self.end_date:
            holidays = get_holidays()
            days_added = 0
            current_date = self.start_date
            while days_added < self.duration_days:
                if current_date.weekday() < 5 and current_date not in holidays:
                    days_added += 1
                    if days_added == self.duration_days:
                        break
                current_date += timedelta(days=1)
            self.end_date = current_date

        super().save(*args, **kwargs)

    @property
    def virtual_duration_days(self):
        if self.duration_days in (20, 25, 30):
            return 60
        return self.duration_days

    @property
    def virtual_daily_payment(self):
        if self.duration_days in (20, 25, 30):
            return (self.total_due / Decimal('60')).quantize(Decimal('0.01'))
        return self.daily_payment

    @property
    def virtual_end_date(self):
        if not self.start_date:
            return self.end_date
        holidays = get_holidays()
        days_added = 0
        current_date = self.start_date
        while days_added < self.virtual_duration_days:
            if current_date.weekday() < 5 and current_date not in holidays:
                days_added += 1
                if days_added == self.virtual_duration_days:
                    break
            current_date += timedelta(days=1)
        return current_date

    # ---------------- Utility methods ----------------

    def _compute_days_elapsed(self, holidays):
        """
        Compute days elapsed using a pre-fetched holiday set.
        Call this from views/loops to avoid repeated DB hits per loan.
        """
        if not self.start_date:
            return 0
        from django.utils import timezone
        today = timezone.localdate()
        if self.is_fully_paid and self.last_paid_date:
            end_date = self.last_paid_date
        else:
            end_date = today
        if self.start_date >= end_date:
            return 0
        count = 0
        current_day = self.start_date
        while current_day < end_date:
            if current_day.weekday() < 5 and current_day not in holidays:
                count += 1
            current_day += timedelta(days=1)
        return count

    @property
    def days_elapsed(self):
        return self._compute_days_elapsed(get_holidays())

    def _compute_days_remaining(self, holidays):
        """
        Remaining working days = duration_days - days_elapsed.
        This is consistent with days_missed = days_elapsed - days_paid.
        Before the loan starts (today < start_date), returns duration_days.
        After end_date, returns 0.
        """
        if not self.virtual_end_date:
            return 0
        from django.utils import timezone
        today = timezone.localdate()
        if today > self.virtual_end_date:
            return 0
        if self.start_date and today < self.start_date:
            return self.virtual_duration_days
        elapsed = self._compute_days_elapsed(holidays)
        return max(self.virtual_duration_days - elapsed, 0)

    @property
    def days_remaining(self):
        return self._compute_days_remaining(get_holidays())

    @property
    def days_missed(self):
        missed = self.days_elapsed - self.days_paid
        return max(missed, 0)
    

    @property
    def payment_cooldown_active(self):
        if not self.last_payment_at:
            return False
        return now() - self.last_payment_at < timedelta(minutes=10)

    @property
    def is_due_today(self):
        if self.status != "active":
            return False
        today = date.today()
        return self.last_paid_date != today

    @property
    def is_fully_paid(self):
        return self.remaining_balance <= 0

    @property
    def remaining_balance(self):
        return max(self.total_due - self.total_paid, 0)

    @property
    def payment_status_color(self):
        if self.days_missed <= 2:
            return "green"
        elif self.days_missed <= 4:
            return "yellow"
        else:
            return "red"

        
    def _next_business_day(self, start_date, holidays=None):
        if not start_date:
            return None
        if holidays is None:
            holidays = get_holidays()
        day = start_date
        while day.weekday() >= 5 or day in holidays:
            day += timedelta(days=1)
        return day


    from django.utils.functional import cached_property

    @cached_property
    def next_payment_date(self):
        if self.is_fully_paid:
            return None

        from django.utils import timezone
        today = timezone.localdate()

        if self.last_paid_date == today:
            base_date = today + timedelta(days=1)
        elif self.days_missed > 0:
            base_date = today
        elif not self.last_paid_date:
            base_date = today
        else:
            base_date = self.last_paid_date + timedelta(days=1)

        next_day = self._next_business_day(base_date)

        if not next_day:
            return None

        delta = (next_day - today).days

        if delta == 0:
            return "Today"
        elif delta == 1:
            return "Tomorrow"
        elif 2 <= delta <= 6:
            return next_day.strftime("On %A")
        else:
            return next_day.strftime("On %d %b %Y")

    def __str__(self):
        return f"{self.customer.name} - {self.principal_amount} SZL"
    
    @property
    def expected_days(self):
        """
        Expected working days depending on loan type
        """
        if self.interest_rate in (20, 25) or self.duration_days in (20, 25, 30):
            return 60
        return self.duration_days

    @property
    def total_working_days(self):
        holidays = get_holidays()

        working_days = 0
        current_date = self.start_date

        while working_days < self.expected_days:
            if current_date.weekday() < 5 and current_date not in holidays:
                working_days += 1
            current_date += timedelta(days=1)

        return working_days
    
    def get_customer_warning(self):
        """
        Returns a warning or encouragement message for this loan.
        Uses the same ladder and rules used for loan eligibility.
        """

        LOAN_LADDER_20 = [250, 500, 1000, 1500, 2000, 2500, 3000, 3500]
        LOAN_LADDER_25 = [400, 500, 600, 1000, 1500, 2000, 2500, 3000, 3500]

        # Select ladder and rules
        if self.interest_rate in (20, 25) or self.duration_days in (20, 25, 30):
            ladder = LOAN_LADDER_20 if self.interest_rate == 20 else LOAN_LADDER_25
            expected_days = 60
            late_cutoff = 62
        else:
            ladder = LOAN_LADDER_25
            expected_days = 25
            late_cutoff = 27

        current_amount = self.principal_amount
        days_missed = self.days_missed
        total_working_days = self.total_working_days

        # Find current index
        try:
            index = ladder.index(current_amount)
        except ValueError:
            return None

        next_upgrade = ladder[min(index + 1, len(ladder) - 1)]
        next_double_upgrade = ladder[min(index + 2, len(ladder) - 1)]
        downgrade = ladder[max(index - 1, 0)]
        heavy_downgrade = ladder[max(index - 2, 0)]

        # 🔴 BLACKLIST CONDITION
        if days_missed > 7 and total_working_days > late_cutoff:
            return (
                "🚨 Urgent: This loan is at risk of blacklisting. "
                "Please pay immediately to avoid losing loan access."
            )

        # 🟢 PERFECT PAYERS
        if days_missed == 0:
            return (
                f"✅ Excellent repayment behaviour. "
                f"Pay within this week and your next loan may increase to {next_double_upgrade} Or within the next two weeks to increase loan to {next_upgrade}."
            )

        # 🟡 SMALL DELAYS
        if days_missed < 3:
            return (
                f"⚠️ Warning: Missing more payments may reduce your next "
                f"loan eligibility to {downgrade}. "
                "Pay within this week to maintain your current limit."
            )

        # 🟠 MODERATE RISK
        if days_missed <= 7:
            return (
                f"⚠️ Your loan eligibility may drop to {heavy_downgrade}. "
                "Please pay within this week to avoid penalties."
            )

        # 🔴 HIGH RISK
        return (
            "🚨 Your account is at high risk. "
            "Pay within this week to avoid blacklisting."
        )
    

class Repayment(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)
    date = models.DateField(default=date.today)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    recorded_by = models.ForeignKey(AgentProfile, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=['loan', 'date']),
            models.Index(fields=['date']),
        ]
        # unique_together = ('loan', 'date')

    def __str__(self):
        return f"{self.loan.customer.name} - {self.amount_paid} on {self.date}"

# loans/models.py



class AdminTransactionRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    TRANSACTION_TYPE_CHOICES = (
        ('withdraw', 'Withdraw from Agent'),
        ('send_to_admin', 'Send Money to Admin'),
    )

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE)
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    actual_received_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES, default='withdraw')
    rejection_note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def approve(self, actual_amount=None):
        """Admin approves and updates agent balance if withdrawal."""
        self.status = 'approved'
        self.actual_received_amount = actual_amount or self.requested_amount

        # Only deduct if it's a withdrawal from agent
        if self.transaction_type == 'withdraw':
            self.agent.amount_in_hand -= self.actual_received_amount
            self.agent.save()

        self.save()



    
class PublicHoliday(models.Model):
    name = models.CharField(max_length=100)
    holiday_date = models.DateField(unique=True)  # renamed

    def __str__(self):
        return f"{self.name} ({self.holiday_date})"

    @staticmethod
    def is_holiday(check_date: date) -> bool:
        return PublicHoliday.objects.filter(holiday_date=check_date).exists()



# loans/models.py
from django.contrib.auth.models import User

class CompanyFinance(models.Model):
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Company Balance: {self.total_amount} SZL"

    @classmethod
    def get_balance(cls):
        """Ensure there’s always exactly one record."""
        obj, created = cls.objects.get_or_create(id=1)
        return obj




class FinanceTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('withdraw', 'Withdraw'),
    ]

    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.transaction_type.title()} of {self.amount} SZL by {self.admin}"


class AgentTransactionLog(models.Model):
    """Records every approved AdminTransactionRequest for an agent's ledger."""
    TRANSACTION_TYPE_CHOICES = (
        ('withdraw', 'Withdraw from Agent'),
        ('send_to_admin', 'Send Money to Admin'),
    )

    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name='transaction_logs')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_agent_transactions')
    transaction_request = models.OneToOneField('AdminTransactionRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='log_entry')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    actual_amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-approved_at']
        indexes = [
            models.Index(fields=['agent', 'approved_at']),
        ]

    def __str__(self):
        return f"{self.agent.user.username} — {self.get_transaction_type_display()} of {self.actual_amount} SZL (approved by {self.approved_by})"


class AgentDailyPerformance(models.Model):
    """
    Snapshot recorded when admin approves a withdrawal.
    One row per agent per day — upserted on each approval so multiple
    withdrawals in a day always reflect the latest figures.
    """
    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name='daily_performances')
    date = models.DateField()

    # Gross: sum of interest earned on loans disbursed that day
    gross_interest = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Total approved withdrawals for that agent on that day
    total_withdrawn = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Net = gross_interest - total_withdrawn
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Loan collection stats for that day
    loans_collected = models.PositiveIntegerField(default=0)
    total_due_loans = models.PositiveIntegerField(default=0)
    collection_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        unique_together = ('agent', 'date')
        ordering = ['-date']
        indexes = [models.Index(fields=['agent', 'date'])]

    def __str__(self):
        return f"{self.agent.user.username} — {self.date} | net {self.net} SZL | {self.collection_percentage}%"


class AILog(models.Model):
    """Logs AI request metadata. Never stores prompts or sensitive data."""
    feature = models.CharField(max_length=100)
    user_role = models.CharField(max_length=30, blank=True, default='')
    model = models.CharField(max_length=100, blank=True, default='')
    provider = models.CharField(max_length=30, blank=True, default='')
    tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True, default='')
    cache_hit = models.BooleanField(default=False)
    tool_used = models.CharField(max_length=100, blank=True, default='')
    intent = models.CharField(max_length=100, blank=True, default='')
    response_time = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['feature', 'created_at'])]


class AdminNotification(models.Model):
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    dismissed_by = models.ManyToManyField(User, blank=True)

    @classmethod
    def create_withdrawal_notice(cls, admin, amount):
        from django.utils import timezone
        expire_time = timezone.now() + timedelta(hours=24)
        cls.objects.create(
            message=f"{admin.username} withdrew {amount} SZL from company funds.",
            expires_at=expire_time
        )

    @classmethod
    def active_for_user(cls, user):
        from django.utils import timezone
        now = timezone.now()
        return cls.objects.filter(
            expires_at__gt=now
        ).exclude(dismissed_by=user)


class PendingLoanApplication(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='pending_applications')
    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE)
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2, default=200.0)
    
    # Store pre-calculated Gemini credit report results
    ai_suggested_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    ai_risk = models.CharField(max_length=20, blank=True, default='')
    ai_confidence = models.IntegerField(null=True, blank=True)
    ai_explanation = models.TextField(blank=True, default='')
    ai_reasons = models.JSONField(null=True, blank=True)
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
