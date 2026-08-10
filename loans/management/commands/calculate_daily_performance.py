from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from accounts.models import AgentProfile
from loans.models import (
    AgentDailyPerformance, AgentTransactionLog, Loan, Repayment,
)


class Command(BaseCommand):
    help = (
        "Calculate and upsert AgentDailyPerformance for all agents. "
        "Run daily via cron to ensure performance data is always up to date, "
        "even when admin approvals are missed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Calculate for a specific date (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to process backwards from the target date. Default: 1.',
        )
        parser.add_argument(
            '--backfill',
            action='store_true',
            help='Only fill missing days. Skips agent/date pairs that already have a '
                 'performance record so existing data is never overwritten.',
        )

    def handle(self, *args, **options):
        target_date = options.get('date')
        days_back = options.get('days', 1)

        if target_date:
            from datetime import date as date_cls
            try:
                end_date = date_cls.fromisoformat(target_date)
            except ValueError:
                self.stderr.write(self.style.ERROR(f'Invalid date: {target_date}. Use YYYY-MM-DD.'))
                return
        else:
            end_date = timezone.localdate()

        start_date = end_date - timedelta(days=days_back - 1)

        self.stdout.write(
            self.style.SUCCESS(f'Calculating performance from {start_date} to {end_date}...')
        )

        agents = AgentProfile.objects.select_related('user').all()
        backfill = options.get('backfill', False)
        total_created = 0
        total_skipped = 0

        for agent in agents:
            for day_offset in range(days_back):
                calc_date = start_date + timedelta(days=day_offset)

                # In backfill mode, skip dates that already have a record
                if backfill and AgentDailyPerformance.objects.filter(
                    agent=agent, date=calc_date
                ).exists():
                    total_skipped += 1
                    continue

                # --- Gross interest: sum of interest on loans disbursed that day ---
                loans_today = Loan.objects.filter(
                    customer__agent=agent,
                    created_at__date=calc_date,
                ).values('principal_amount', 'interest_rate')

                gross_interest = sum(
                    l['principal_amount'] * l['interest_rate'] / Decimal('100')
                    for l in loans_today
                )

                # --- Total withdrawn: approved withdrawals + send_to_admin for that day ---
                total_withdrawn = AgentTransactionLog.objects.filter(
                    agent=agent,
                    approved_at__date=calc_date,
                    transaction_type__in=['withdraw', 'send_to_admin'],
                ).aggregate(total=Sum('actual_amount'))['total'] or Decimal('0')

                # --- Collection stats ---
                active_loans = Loan.objects.filter(customer__agent=agent, status='active')
                total_due = active_loans.count()
                collected = active_loans.filter(
                    repayment__date=calc_date
                ).distinct().count()
                collection_pct = round((collected / total_due) * 100, 2) if total_due else 0

                # --- Upsert or insert (backfill mode preserves existing records) ---
                AgentDailyPerformance.objects.update_or_create(
                    agent=agent,
                    date=calc_date,
                    defaults=dict(
                        gross_interest=gross_interest,
                        total_withdrawn=total_withdrawn,
                        net=gross_interest - total_withdrawn,
                        loans_collected=collected,
                        total_due_loans=total_due,
                        collection_percentage=collection_pct,
                    ),
                )
                total_created += 1

        summary = f'Done. Created {total_created} performance record(s)'
        if backfill:
            summary += f', skipped {total_skipped} existing day(s)'
        summary += f' for {agents.count()} agent(s).'
        self.stdout.write(self.style.SUCCESS(summary))
