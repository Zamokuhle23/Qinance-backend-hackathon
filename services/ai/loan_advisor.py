import json
from .ai_service import AIService
from .prompt_builder import PromptBuilder


class LoanAdvisor:
    """AI loan advisory for agents. Gemini NEVER approves loans — only advises."""

    def __init__(self):
        self.ai_service = AIService()

    def get_loan_advice(self, customer, requested_amount=None):
        from loans.models import Loan, Repayment, LoanSettings

        loans = Loan.objects.filter(customer=customer).order_by('-created_at')
        total = loans.count()
        completed = loans.filter(status='completed').count()
        active = loans.filter(status='active').count()
        defaulted = sum(1 for l in loans if l.days_missed > 7)
        delays = sum(1 for l in loans if 0 < l.days_missed <= 7)

        repayments = Repayment.objects.filter(loan__customer=customer)
        total_rep = repayments.count()
        on_time = sum(1 for r in repayments if r.loan.days_missed == 0)
        consistency = round((on_time / total_rep) * 100, 1) if total_rep else 0

        profile = {
            'name': customer.name,
            'location': customer.location or 'Unknown',
            'credit_score': customer.credit_score,
            'blacklisted': customer.blacklisted,
            'has_active_loan': customer.has_active_loan,
        }
        loan_summary = {
            'total_loans': total, 'completed_loans': completed,
            'active_loans': active, 'defaulted_loans': defaulted,
            'payment_delays': delays,
        }
        repayment_summary = {
            'total_repayments': total_rep, 'on_time_percentage': consistency,
        }

        # 1. Deterministic Python limit using pre-calculated customer.credit_score directly
        settings = LoanSettings.objects.first()
        python_ceiling = float(customer.credit_score) if customer.credit_score else (float(settings.max_loan_amount) if settings else 500.0)

        # Define Gemini cap with some room (+15%)
        gemini_cap = round(python_ceiling * 1.15, 2)

        # 1b. Enhanced repayment metrics based on repayment history (if exists)
        repayment_stats = {}
        if last_loan:
            repayments_last = Repayment.objects.filter(loan=last_loan)
            if repayments_last.exists():
                from django.db.models import Avg, Max, Min
                repayment_stats = {
                    'average_daily_payment_made': float(repayments_last.aggregate(avg=Avg('amount_paid'))['avg'] or 0),
                    'maximum_daily_payment_made': float(repayments_last.aggregate(max=Max('amount_paid'))['max'] or 0),
                    'minimum_daily_payment_made': float(repayments_last.aggregate(min=Min('amount_paid'))['min'] or 0),
                    'days_missed_on_last_loan': last_loan.days_missed,
                    'required_daily_payment_on_last_loan': float(last_loan.daily_payment),
                }
            else:
                repayment_stats = {
                    'days_missed_on_last_loan': last_loan.days_missed,
                    'required_daily_payment_on_last_loan': float(last_loan.daily_payment),
                }
        
        repayment_summary.update(repayment_stats)

        # 2. Enrich profile context with calculated limits and location
        profile['deterministic_ceiling'] = python_ceiling
        profile['gemini_absolute_cap'] = gemini_cap
        profile['merchant_location'] = customer.location or 'Unknown'

        prompt = PromptBuilder.build_loan_advisor_prompt(
            json.dumps(profile), json.dumps(loan_summary), json.dumps(repayment_summary)
        )
        result = self.ai_service.generate_json(
            prompt, system_prompt=PromptBuilder.LOAN_ADVISOR_SYSTEM,
            feature='loan_advisor', user_role='agent',
        )
        if not result['success']:
            return {'success': False, 'error': result['error'], 'advice': None}

        advice = result['data'] or {}
        
        # 3. Post-validation: Forcefully apply guardrails on Gemini's response
        suggested = float(advice.get('suggested_loan_amount', 0) or 0)
        if suggested > gemini_cap:
            advice['suggested_loan_amount'] = gemini_cap
            if 'explanation' in advice:
                advice['explanation'] += f" [Note: AI suggested amount was capped at the absolute limit of E{gemini_cap:.2f} due to risk management parameters.]"

        return {
            'success': True, 
            'advice': advice,
            'tokens': result.get('tokens', 0), 
            'latency_ms': result.get('latency_ms', 0),
        }
