from decimal import Decimal

from django.test import SimpleTestCase

from loans.models import Loan


class LoanDurationPolicyTests(SimpleTestCase):
    def test_virtual_duration_uses_60_day_regulatory_standard(self):
        loan = Loan(
            principal_amount=Decimal('1000.00'),
            interest_rate=Decimal('20'),
            duration_days=30,
            total_due=Decimal('1200.00'),
        )

        self.assertEqual(loan.virtual_duration_days, 60)
        self.assertEqual(loan.virtual_daily_payment, Decimal('20.00'))

    def test_shortened_internal_duration_maps_to_60_day_regulatory_standard(self):
        loan = Loan(
            principal_amount=Decimal('1000.00'),
            interest_rate=Decimal('20'),
            duration_days=20,
            total_due=Decimal('1200.00'),
        )

        self.assertEqual(loan.virtual_duration_days, 60)
