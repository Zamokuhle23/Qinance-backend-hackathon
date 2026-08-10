"""BusinessAdvisor — deterministic Python calculations + Gemini explanation.

Python computes the business health score from repayment data.
Gemini only explains those numbers in plain language.
No customer PII (name, exact credit score) is ever sent to Gemini.
"""

import json
from decimal import Decimal

from .ai_service import AIService
from .prompt_builder import PromptBuilder


def _band(score):
    if score is None:
        return 'unknown'
    if score >= 750:
        return 'excellent'
    if score >= 650:
        return 'good'
    if score >= 500:
        return 'fair'
    return 'poor'


class BusinessAdvisor:
    """AI business health advisor. Advisory only — never makes financial decisions."""

    def __init__(self):
        self.ai_service = AIService()

    def _calculate_health(self, customer):
        """Deterministic Python business rules. Never sends raw PII to Gemini."""
        from loans.models import Loan, Repayment

        loans = Loan.objects.filter(customer=customer)
        total = loans.count()
        completed = loans.filter(status='completed').count()
        active = loans.filter(status='active').count()
        defaulted = sum(1 for l in loans if l.days_missed > 7)
        delays = sum(1 for l in loans if 0 < l.days_missed <= 7)

        repayments = Repayment.objects.filter(loan__customer=customer)
        total_rep = repayments.count()
        on_time = sum(1 for r in repayments if r.loan.days_missed == 0)
        consistency = round((on_time / total_rep) * 100, 1) if total_rep else 0

        # Deterministic health score from Python — Gemini never computes this.
        score = Decimal('50')
        score += Decimal(str(consistency)) / Decimal('5')   # up to +20
        score += Decimal(str(completed)) * Decimal('3')      # +3 per completed loan
        score -= Decimal(str(defaulted)) * Decimal('15')     # -15 per default
        score -= Decimal(str(delays)) * Decimal('2')         # -2 per delay
        score = max(Decimal('0'), min(Decimal('100'), score))

        if score >= 80:
            label = 'Excellent'
        elif score >= 60:
            label = 'Good'
        elif score >= 40:
            label = 'Average'
        else:
            label = 'Needs Attention'

        return {
            'credit_score_band': _band(customer.credit_score),
            'blacklisted': customer.blacklisted,
            'total_loans': total,
            'completed_loans': completed,
            'active_loans': active,
            'defaulted_loans': defaulted,
            'payment_delays': delays,
            'repayment_consistency_pct': consistency,
            'business_health': float(score.quantize(Decimal('0.01'))),
            'health_label': label,
        }

    def get_business_health(self, customer):
        summary = self._calculate_health(customer)

        prompt = PromptBuilder.build_business_health_prompt(json.dumps(summary))
        result = self.ai_service.generate_json(
            prompt,
            system_prompt=PromptBuilder.BUSINESS_HEALTH_SYSTEM,
            feature='business_health',
            user_role='agent',
            intent='business_health',
        )
        if not result['success']:
            return {'success': False, 'error': result['error'], 'health': None}

        health = result['data'] or {}
        # Keep the deterministic Python values — Gemini never overrides them.
        health['business_health'] = summary['business_health']
        health['health_label'] = summary['health_label']

        return {
            'success': True,
            'health': health,
            'tokens': result.get('tokens', 0),
            'latency_ms': result.get('latency_ms', 0),
        }