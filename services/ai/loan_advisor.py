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

        # 1b. Chronological repayment history paragraphs for all loans (showing shifts in behavior)
        loans_history_detail = []
        past_loans_list = list(Loan.objects.filter(customer=customer).order_by('created_at'))
        
        for idx, l in enumerate(past_loans_list, 1):
            repayments_last = Repayment.objects.filter(loan=l)
            if repayments_last.exists():
                from django.db.models import Avg, Max, Min
                avg_pay = float(repayments_last.aggregate(avg=Avg('amount_paid'))['avg'] or 0)
                max_pay = float(repayments_last.aggregate(max=Max('amount_paid'))['max'] or 0)
                min_pay = float(repayments_last.aggregate(min=Min('amount_paid'))['min'] or 0)
                detail_paragraph = (
                    f"Loan #{idx} (Principal: E{float(l.principal_amount):.2f}, Interest: {l.interest_rate}%, Status: {l.status}): "
                    f"Active from {l.start_date} to {l.end_date}. Required daily payment was E{float(l.daily_payment):.2f}. "
                    f"Repayment behaviour: made {repayments_last.count()} total repayments. Average daily amount paid was E{avg_pay:.2f}, "
                    f"maximum single day paid was E{max_pay:.2f}, minimum single day paid was E{min_pay:.2f}. "
                    f"Days missed on this loan: {l.days_missed}."
                )
            else:
                detail_paragraph = (
                    f"Loan #{idx} (Principal: E{float(l.principal_amount):.2f}, Interest: {l.interest_rate}%, Status: {l.status}): "
                    f"Active from {l.start_date} to {l.end_date}. Required daily payment was E{float(l.daily_payment):.2f}. "
                    f"No repayments made yet. Days missed: {l.days_missed}."
                )
            loans_history_detail.append(detail_paragraph)

        repayment_summary['chronological_loan_history_paragraphs'] = loans_history_detail

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
