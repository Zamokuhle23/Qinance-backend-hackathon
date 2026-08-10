"""Agent tools for Ask Qinance — merchant-backend.

Agent tools summarise customer, loan, and repayment data from the microfinance
backend. Gemini never queries PostgreSQL directly — these tools do.
"""

from decimal import Decimal

from .registry import register_tool


def _band(score):
    """Convert a credit score into a band — never send exact scores to Gemini."""
    if score is None:
        return 'unknown'
    if score >= 750:
        return 'excellent'
    if score >= 650:
        return 'good'
    if score >= 500:
        return 'fair'
    return 'poor'


def _anonymised_summary(customer):
    """Build an anonymised customer summary. Never send name/location to Gemini."""
    from loans.models import Loan, Repayment, LoanSettings

    loans = Loan.objects.filter(customer=customer).order_by('-created_at')
    repayments = Repayment.objects.filter(loan__customer=customer)

    total_loans = loans.count()
    completed = loans.filter(status='completed').count()
    active = loans.filter(status='active').count()
    defaulted = sum(1 for l in loans if l.days_missed > 7)
    delays = sum(1 for l in loans if 0 < l.days_missed <= 7)

    total_rep = repayments.count()
    on_time = sum(1 for r in repayments if r.loan.days_missed == 0)
    consistency = round((on_time / total_rep) * 100, 1) if total_rep else 0

    # Deterministic recommended limit — Python calculates, Gemini explains.
    settings = LoanSettings.objects.first()
    max_loan = Decimal(str(settings.max_loan_amount)) if settings else Decimal('5000')

    base = Decimal(str(customer.credit_score or 0)) / Decimal('100')
    if consistency and total_rep:
        base = base * Decimal('0.6') + (Decimal(str(consistency)) / Decimal('100')) * Decimal('0.4')
    if customer.blacklisted:
        base = base * Decimal('0')
    elif defaulted:
        base = base * Decimal('0.5') / Decimal(str(defaulted))
    recommended = min(max_loan, max_loan * base)

    return {
        'credit_score_band': _band(customer.credit_score),
        'blacklisted': customer.blacklisted,
        'has_active_loan': customer.has_active_loan,
        'total_loans': total_loans,
        'completed_loans': completed,
        'active_loans': active,
        'defaulted_loans': defaulted,
        'payment_delays': delays,
        'on_time_percentage': consistency,
        'recommended_max_loan': float(recommended.quantize(Decimal('0.01'))),
    }


@register_tool(
    'customer_summary',
    roles=['customer', 'agent', 'admin'],
    description='Summarise a customer loan profile. Returns anonymised credit band, loan counts, repayment consistency.',
)
def customer_summary(customer_id):
    from loans.models import Customer
    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return {'ok': False, 'error': f'Customer {customer_id} not found'}
    return {'ok': True, 'data': _anonymised_summary(customer)}


@register_tool(
    'loan_summary',
    roles=['agent', 'merchant', 'admin'],
    description='Summarise loans for a customer or agent. Returns counts by status and outstanding amounts.',
)
def loan_summary(customer_id=None, agent_id=None):
    from loans.models import Loan
    from django.db.models import Sum

    qs = Loan.objects.all()
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if agent_id:
        qs = qs.filter(customer__agent_id=agent_id)

    active_qs = qs.filter(status='active')
    return {
        'ok': True,
        'data': {
            'total_loans': qs.count(),
            'active_loans': active_qs.count(),
            'completed_loans': qs.filter(status='completed').count(),
            'defaulted_loans': qs.filter(status='defaulted').count(),
            'outstanding_principal': float(
                active_qs.aggregate(total=Sum('principal_amount'))['total'] or 0
            ),
        }
    }


@register_tool(
    'repayment_summary',
    roles=['agent', 'merchant', 'admin'],
    description='Summarise repayment behaviour for a customer. Returns on-time percentage and delay counts.',
)
def repayment_summary(customer_id=None, agent_id=None):
    from loans.models import Repayment, Loan

    loans = Loan.objects.all()
    if customer_id:
        loans = loans.filter(customer_id=customer_id)
    if agent_id:
        loans = loans.filter(customer__agent_id=agent_id)
    repayments = Repayment.objects.filter(loan__in=loans)

    total = repayments.count()
    on_time = sum(1 for r in repayments if r.loan.days_missed == 0)
    return {
        'ok': True,
        'data': {
            'total_repayments': total,
            'on_time_percentage': round((on_time / total) * 100, 1) if total else 0,
            'late_repayments': total - on_time,
        }
    }


@register_tool(
    'risk_summary',
    roles=['agent', 'admin'],
    description='Summarise customer risk. Returns risk level and reasons.',
)
def risk_summary(customer_id):
    from loans.models import Customer
    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return {'ok': False, 'error': f'Customer {customer_id} not found'}

    data = _anonymised_summary(customer)
    reasons = []
    risk = 'low'
    if customer.blacklisted:
        risk = 'high'
        reasons.append('Blacklisted')
    if data['defaulted_loans'] > 0:
        risk = 'high'
        reasons.append(f"{data['defaulted_loans']} defaulted loan(s)")
    if data['payment_delays'] > 0:
        risk = 'medium' if risk == 'low' else risk
        reasons.append(f"{data['payment_delays']} payment delay(s)")
    if data['on_time_percentage'] < 60 and data['total_loans'] > 0:
        risk = 'medium' if risk == 'low' else risk
        reasons.append('Low repayment consistency')
    if not reasons:
        reasons.append('No significant risk factors')

    return {'ok': True, 'data': {'risk': risk, 'reasons': reasons}}


@register_tool(
    'recommended_limit',
    roles=['customer', 'agent', 'admin'],
    description='Calculate a recommended loan limit for a customer using deterministic Python business rules.',
)
def recommended_limit(customer_id):
    from loans.models import Customer
    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return {'ok': False, 'error': f'Customer {customer_id} not found'}

    data = _anonymised_summary(customer)
    return {
        'ok': True,
        'data': {
            'recommended_max_loan': data['recommended_max_loan'],
            'calculation': 'Python deterministic calculation based on credit band and repayment consistency.',
        }
    }


@register_tool(
    'loan_explainability',
    roles=['agent', 'merchant', 'admin'],
    description=(
        'AI Loan Explainability. Takes the traditional risk engine\'s safe loan '
        'range and layers Gemini context (weather, events, seasonality, repayment '
        'history) to recommend an amount WITHIN the approved range with an '
        'explanation and confidence. Never overrides lending guardrails.'
    ),
)
def loan_explainability(customer_id, risk_score='low', loan_range_lower=0, loan_range_upper=0):
    """Deterministic context gathering — Gemini only explains within the safe range."""
    from loans.models import Customer
    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return {'ok': False, 'error': f'Customer {customer_id} not found'}

    data = _anonymised_summary(customer)
    return {
        'ok': True,
        'data': {
            'credit_score_band': data['credit_score_band'],
            'blacklisted': data['blacklisted'],
            'has_active_loan': data['has_active_loan'],
            'completed_loans': data['completed_loans'],
            'defaulted_loans': data['defaulted_loans'],
            'payment_delays': data['payment_delays'],
            'on_time_percentage': data['on_time_percentage'],
            'traditional_risk_score': risk_score,
            'approved_loan_range': [float(loan_range_lower), float(loan_range_upper)],
            'context_hints': {
                'weather': 'Check local weather forecast for the week.',
                'events': 'Check for nearby events/tournaments this weekend.',
                'seasonality': 'Consider business type seasonality.',
            },
        }
    }
