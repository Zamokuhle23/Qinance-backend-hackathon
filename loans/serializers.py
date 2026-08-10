from rest_framework import serializers
from .models import (
    Customer, Loan, Repayment, LoanSettings,
    AgentDailyPerformance, AdminTransactionRequest,
    AgentTransactionLog, FinanceTransaction, AdminNotification,
)
from accounts.models import AgentProfile
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    agent_id = serializers.SerializerMethodField()
    amount_in_hand = serializers.SerializerMethodField()

    def get_agent_id(self, obj):
        try:
            return obj.agentprofile.id
        except Exception:
            return None

    def get_amount_in_hand(self, obj):
        try:
            return str(obj.agentprofile.amount_in_hand)
        except Exception:
            return None

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_staff', 'agent_id', 'amount_in_hand']


class AgentProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = AgentProfile
        fields = ['id', 'username', 'email', 'phone', 'address', 'amount_in_hand', 'is_active']


class CustomerSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source='agent.user.username', read_only=True)
    agent_id = serializers.IntegerField(source='agent.id', read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'location', 'national_id', 'created_at',
            'credit_score', 'blacklisted', 'has_active_loan', 'agent_name', 'agent_id',
        ]


class RepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repayment
        fields = ['id', 'date', 'amount_paid']


class LoanSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    remaining_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    duration_days = serializers.IntegerField(source='virtual_duration_days', read_only=True)
    daily_payment = serializers.DecimalField(source='virtual_daily_payment', max_digits=10, decimal_places=2, read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    days_missed = serializers.IntegerField(read_only=True)
    payment_status_color = serializers.CharField(read_only=True)
    is_fully_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id', 'customer_id', 'customer_name', 'customer_phone',
            'principal_amount', 'interest_rate', 'total_due', 'daily_payment',
            'duration_days', 'start_date', 'end_date', 'status',
            'days_paid', 'total_paid', 'remaining_balance', 'days_remaining',
            'days_missed', 'payment_status_color', 'is_fully_paid',
            'last_payment_at', 'created_at',
        ]


class DueLoanSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    remaining_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    daily_payment = serializers.DecimalField(source='virtual_daily_payment', max_digits=10, decimal_places=2, read_only=True)
    payment_status_color = serializers.CharField(read_only=True)
    paid_today = serializers.BooleanField(read_only=True)
    amount_paid_today = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()

    def get_amount_paid_today(self, obj):
        val = getattr(obj, 'amount_paid_today', 0)
        return str(val) if val else '0.00'

    def get_days_remaining(self, obj):
        if hasattr(obj, 'days_remaining_cached'):
            return obj.days_remaining_cached
        holidays = self.context.get('holidays', set())
        return obj._compute_days_remaining(holidays)

    class Meta:
        model = Loan
        fields = [
            'id', 'customer_id', 'customer_name', 'customer_phone',
            'principal_amount', 'daily_payment', 'total_due',
            'total_paid', 'remaining_balance', 'days_remaining',
            'payment_status_color', 'paid_today', 'amount_paid_today',
        ]


class LoanSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanSettings
        fields = '__all__'


class AgentDailyPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDailyPerformance
        fields = '__all__'


class AdminTransactionRequestSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source='agent.user.username', read_only=True)

    class Meta:
        model = AdminTransactionRequest
        fields = '__all__'


class AgentTransactionLogSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source='agent.user.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = AgentTransactionLog
        fields = '__all__'


class FinanceTransactionSerializer(serializers.ModelSerializer):
    admin_name = serializers.SerializerMethodField()

    def get_admin_name(self, obj):
        return obj.admin.username if obj.admin else ''

    class Meta:
        model = FinanceTransaction
        fields = '__all__'


class AdminNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminNotification
        fields = ['id', 'message', 'created_at', 'expires_at']


from .models import PendingLoanApplication

class PendingLoanApplicationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    customer_location = serializers.CharField(source='customer.location', read_only=True)
    customer_credit_score = serializers.IntegerField(source='customer.credit_score', read_only=True)

    class Meta:
        model = PendingLoanApplication
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'customer_location', 'customer_credit_score',
            'requested_amount', 'ai_suggested_amount', 'ai_risk', 'ai_confidence',
            'ai_explanation', 'ai_reasons', 'status', 'created_at'
        ]
