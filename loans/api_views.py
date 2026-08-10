from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AgentProfile, RegistrationToken
from .models import (
    AdminNotification, AdminTransactionRequest, AgentDailyPerformance,
    AgentTransactionLog, CompanyFinance, Customer, FinanceTransaction,
    Loan, LoanSettings, PublicHoliday, Repayment, get_holidays,
)
from .serializers import (
    AdminNotificationSerializer, AdminTransactionRequestSerializer,
    AgentDailyPerformanceSerializer, AgentProfileSerializer,
    AgentTransactionLogSerializer, CustomerSerializer, DueLoanSerializer,
    FinanceTransactionSerializer, LoanSerializer, LoanSettingsSerializer,
    UserSerializer,
)
from .views import evaluate_customer_loan_range, LOAN_LADDER_20, LOAN_LADDER_25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_staff(user):
    return user.is_staff or user.is_superuser


class IsStaff(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and is_staff(request.user)


# ---------------------------------------------------------------------------
# Agent — Dashboard
# ---------------------------------------------------------------------------

class AgentDashboardAPIView(APIView):
    def get(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = timezone.localdate()

        active_loans = list(
            Loan.objects.filter(customer__agent=agent_profile, status='active')
            .select_related('customer')
            .annotate(
                amount_paid_today=Sum(
                    'repayment__amount_paid',
                    filter=Q(repayment__date=today),
                    default=0,
                ),
                paid_today=Exists(
                    Repayment.objects.filter(loan=OuterRef('pk'), date=today)
                ),
            )
            .order_by('display_order', Lower('customer__name'))
        )

        holidays = get_holidays()
        for loan in active_loans:
            loan.days_remaining_cached = loan._compute_days_remaining(holidays)

        due_loans = [l for l in active_loans if not l.paid_today]
        loans_paid = [l for l in active_loans if l.paid_today]

        amount_collected = (
            Repayment.objects.filter(loan__customer__agent=agent_profile, date=today)
            .aggregate(total=Sum('amount_paid'))['total'] or 0
        )
        loans_collected_count = (
            Repayment.objects.filter(loan__customer__agent=agent_profile, date=today)
            .values('loan').distinct().count()
        )
        amount_to_collect = sum(l.daily_payment for l in active_loans)
        completed_today = Loan.objects.filter(
            customer__agent=agent_profile,
            status='completed',
            repayment__date=today,
        ).distinct().count()
        total_due_loans = len(active_loans) + completed_today
        performance = round((loans_collected_count / total_due_loans) * 100, 2) if total_due_loans else 0

        loans_taken_today = list(
            Loan.objects.filter(customer__agent=agent_profile, created_at__date=today)
            .select_related('customer')
            .order_by(Lower('customer__name'))
        )

        return Response({
            'agent': AgentProfileSerializer(agent_profile).data,
            'metrics': {
                'amount_in_hand': str(agent_profile.amount_in_hand),
                'amount_collected': str(amount_collected),
                'amount_to_collect': str(amount_to_collect),
                'loans_collected_count': loans_collected_count,
                'total_due_loans': total_due_loans,
                'performance': performance,
                'total_customers': Customer.objects.filter(agent=agent_profile).count(),
            },
            'due_loans': DueLoanSerializer(due_loans, many=True, context={'holidays': holidays}).data,
            'loans_paid': DueLoanSerializer(loans_paid, many=True, context={'holidays': holidays}).data,
            'loans_taken_today': LoanSerializer(loans_taken_today, many=True).data,
        })


# ---------------------------------------------------------------------------
# Agent — Mark / Reverse payment
# ---------------------------------------------------------------------------

class MarkPaymentAPIView(APIView):
    def post(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = date.today()
        now_time = timezone.now()

        try:
            amount = Decimal(str(request.data.get('amount', loan.daily_payment)))
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if loan.last_payment_at and (now_time - loan.last_payment_at) < timedelta(minutes=10):
            return Response(
                {'error': 'Payment already recorded. Wait 10 minutes before retrying.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        is_first_today = not Repayment.objects.filter(loan=loan, date=today).exists()

        Repayment.objects.create(loan=loan, date=today, amount_paid=amount, recorded_by=agent_profile)
        loan.total_paid += amount
        loan.last_payment_at = now_time
        loan.last_paid_date = today
        if is_first_today:
            loan.days_paid += 1
        agent_profile.amount_in_hand += amount
        agent_profile.save()

        completed = False
        messages_out = []
        if loan.remaining_balance <= 0:
            loan.status = 'completed'
            completed = True
            lower, upper, blacklist = evaluate_customer_loan_range(loan)
            customer = loan.customer
            customer.credit_score = upper
            if blacklist:
                customer.blacklisted = True
                messages_out.append('Customer blacklisted due to payment history.')
            customer.save()
            messages_out.insert(0, f'Loan #{loan.id} fully paid and marked completed.')

        loan.save()
        cache.delete(f'agent_dashboard_{request.user.id}')

        return Response({
            'ok': True,
            'completed': completed,
            'remaining_balance': str(loan.remaining_balance),
            'amount_in_hand': str(agent_profile.amount_in_hand),
            'messages': messages_out,
        })


class ReversePaymentAPIView(APIView):
    @transaction.atomic
    def post(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)
        agent_profile = get_object_or_404(AgentProfile, user=request.user)

        if loan.customer.agent != agent_profile:
            return Response({'error': 'Unauthorized.'}, status=status.HTTP_403_FORBIDDEN)

        today = date.today()
        repayment = Repayment.objects.filter(loan=loan, date=today).order_by('-id').first()
        if not repayment:
            return Response({'error': 'No payment today to reverse.'}, status=status.HTTP_400_BAD_REQUEST)

        amount = repayment.amount_paid
        agent_profile.amount_in_hand -= amount
        loan.total_paid -= amount
        agent_profile.save()
        loan.save()
        repayment.delete()

        last = Repayment.objects.filter(loan=loan).order_by('-date', '-id').first()
        loan.last_paid_date = last.date if last else None
        loan.last_payment_at = last.date if last else None
        loan.save()
        cache.delete(f'agent_dashboard_{request.user.id}')

        return Response({'ok': True, 'reversed_amount': str(amount)})


# ---------------------------------------------------------------------------
# Agent — Customers
# ---------------------------------------------------------------------------

class CustomerListAPIView(APIView):
    def get(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        customers = (
            Customer.objects.filter(agent=agent_profile)
            .annotate(total_loans=Count('loan'))
            .order_by('name')
        )
        serializer = CustomerSerializer(customers, many=True)
        data = serializer.data
        # attach total_loans annotation
        for item, obj in zip(data, customers):
            item['total_loans'] = obj.total_loans
        return Response(data)


class CreateCustomerLoanAPIView(APIView):
    def post(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        name = request.data.get('name', '').strip()
        phone = request.data.get('phone', '').strip()
        national_id = request.data.get('national_id', '').strip()
        location = request.data.get('location', '').strip()

        if not name or not phone or not national_id:
            return Response({'error': 'name, phone and national_id are required.'}, status=400)

        if Customer.objects.filter(national_id=national_id).exists():
            return Response({'error': 'A customer with this national ID already exists.'}, status=400)

        settings = LoanSettings.objects.first()
        credit_score = int(settings.max_loan_amount) if settings else 500

        customer = Customer.objects.create(
            agent=agent_profile,
            name=name,
            phone=phone,
            national_id=national_id,
            location=location,
            credit_score=credit_score,
        )
        return Response(CustomerSerializer(customer).data, status=201)


class AddLoanExistingAPIView(APIView):
    def post(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        customer_id = request.data.get('customer_id')
        customer = get_object_or_404(Customer, id=customer_id, agent=agent_profile)

        if customer.blacklisted:
            return Response({'error': 'Customer is blacklisted.'}, status=400)
        if Loan.objects.filter(customer=customer, status='active').exists():
            return Response({'error': 'Customer already has an active loan.'}, status=400)

        try:
            amount = Decimal(str(request.data.get('amount')))
            interest = Decimal(str(request.data.get('interest', 20)))
            days = int(request.data.get('days', 20))
        except Exception:
            return Response({'error': 'Invalid loan parameters.'}, status=400)

        if amount > agent_profile.amount_in_hand:
            return Response({'error': f'Insufficient cash. You have {agent_profile.amount_in_hand} SZL.'}, status=400)

        total_due = amount + (amount * interest / 100)
        daily_payment = total_due / days

        with transaction.atomic():
            loan = Loan.objects.create(
                customer=customer,
                principal_amount=amount,
                interest_rate=interest,
                duration_days=days,
                total_due=total_due.quantize(Decimal('0.01')),
                daily_payment=daily_payment.quantize(Decimal('0.01')),
                status='active',
            )
            agent_profile.amount_in_hand -= amount
            agent_profile.save(update_fields=['amount_in_hand'])

        return Response(LoanSerializer(loan).data, status=201)


class LoanQualificationAPIView(APIView):
    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)

        if customer.blacklisted:
            return Response({'error': 'Customer is blacklisted.'}, status=400)
        if Loan.objects.filter(customer=customer, status='active').exists():
            return Response({'error': 'Customer has an active loan.'}, status=400)

        settings = LoanSettings.objects.first()
        lower = int(settings.min_loan_amount) if settings else 200
        upper = customer.credit_score

        return Response({
            'customer': CustomerSerializer(customer).data,
            'lower': lower,
            'upper': upper,
        })


class LoanOfferAPIView(APIView):
    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        try:
            amount = float(request.query_params.get('amount', 250))
        except ValueError:
            amount = 250

        offers = []
        for interest, days in [(20, 20), (25, 25)]:
            total_due = round(amount + amount * interest / 100, 2)
            offers.append({
                'interest': interest,
                'days': days,
                'total_due': total_due,
                'daily_payment': round(total_due / days, 2),
            })
        return Response({'customer': CustomerSerializer(customer).data, 'amount': amount, 'offers': offers})

    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        agent_profile = get_object_or_404(AgentProfile, user=request.user)

        if customer.blacklisted:
            return Response({'error': 'Customer is blacklisted.'}, status=400)
        if Loan.objects.filter(customer=customer, status='active').exists():
            return Response({'error': 'Customer already has an active loan.'}, status=400)

        try:
            interest = Decimal(str(request.data.get('interest')))
            days = int(request.data.get('days'))
            amount = Decimal(str(request.data.get('amount')))
        except Exception:
            return Response({'error': 'Invalid parameters.'}, status=400)

        if amount > agent_profile.amount_in_hand:
            return Response({'error': f'Insufficient cash ({agent_profile.amount_in_hand} SZL).'}, status=400)

        total_due = amount + (amount * interest / 100)
        daily_payment = total_due / days

        with transaction.atomic():
            loan = Loan.objects.create(
                customer=customer,
                principal_amount=amount,
                interest_rate=interest,
                duration_days=days,
                total_due=total_due.quantize(Decimal('0.01')),
                daily_payment=daily_payment.quantize(Decimal('0.01')),
                status='active',
            )
            agent_profile.amount_in_hand -= amount
            agent_profile.save(update_fields=['amount_in_hand'])

        return Response(LoanSerializer(loan).data, status=201)


class CustomerHistoryAPIView(APIView):
    def get(self, request, customer_id, loan_id=None):
        customer = get_object_or_404(Customer, id=customer_id)
        today = timezone.now().date()

        if loan_id:
            loan = get_object_or_404(Loan, id=loan_id, customer=customer)
        else:
            loan = Loan.objects.filter(customer=customer).order_by('-start_date').first()

        loans_list = Loan.objects.filter(customer=customer).order_by('-start_date')

        history = []
        if loan:
            repayments = Repayment.objects.filter(loan=loan).order_by('date', 'id')
            payments_by_date = {}
            for r in repayments:
                payments_by_date.setdefault(r.date, []).append(float(r.amount_paid))

            total_paid = repayments.aggregate(total=Sum('amount_paid'))['total'] or 0
            total_required = float(loan.principal_amount) + float(loan.principal_amount) * float(loan.interest_rate) / 100
            last_payment_date = repayments.last().date if repayments.exists() else None
            is_closed = float(total_paid) >= total_required
            end_date = last_payment_date if (is_closed and last_payment_date) else today

            holidays = set(PublicHoliday.objects.values_list('holiday_date', flat=True))
            current_day = loan.start_date

            if loan.created_at:
                history.append({
                    'date': str(loan.created_at.date()),
                    'type': 'disbursed',
                    'label': f'Loan disbursed – E{float(loan.principal_amount):.2f}',
                })

            while current_day <= end_date:
                if current_day.weekday() >= 5 or current_day in holidays:
                    current_day += timedelta(days=1)
                    continue
                if current_day in payments_by_date:
                    payments = payments_by_date[current_day]
                    total_day = sum(payments)
                    breakdown = ', '.join(f'E{p:.2f}' for p in payments)
                    history.append({
                        'date': str(current_day),
                        'type': 'paid',
                        'label': f'Payment received – E{total_day:.2f} [{breakdown}]',
                    })
                else:
                    history.append({'date': str(current_day), 'type': 'missed', 'label': 'Missed payment'})
                current_day += timedelta(days=1)

        return Response({
            'customer': CustomerSerializer(customer).data,
            'loan': LoanSerializer(loan).data if loan else None,
            'loans': LoanSerializer(loans_list, many=True).data,
            'history': history,
        })


# ---------------------------------------------------------------------------
# Agent — Loan display order
# ---------------------------------------------------------------------------

class ReorderLoansAPIView(APIView):
    def post(self, request):
        from django.db.models import Case, When, IntegerField as IntF
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        order_data = request.data
        if not isinstance(order_data, list):
            return Response({'error': 'Expected a list.'}, status=400)
        loan_ids = [item['loan_id'] for item in order_data]
        whens = [When(id=item['loan_id'], then=item['display_order']) for item in order_data]
        Loan.objects.filter(
            id__in=loan_ids, customer__agent=agent_profile
        ).update(display_order=Case(*whens, output_field=IntF()))
        return Response({'status': 'ok'})


# ---------------------------------------------------------------------------
# Agent — Batch collect / payment
# ---------------------------------------------------------------------------

class BatchCollectAPIView(APIView):
    def get(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = timezone.localdate()
        active_loans = (
            Loan.objects.filter(customer__agent=agent_profile, status='active')
            .select_related('customer')
            .annotate(paid_today=Exists(Repayment.objects.filter(loan=OuterRef('pk'), date=today)))
            .order_by('display_order', Lower('customer__name'))
        )
        holidays = get_holidays()
        due_loans = []
        for loan in active_loans:
            if not loan.paid_today:
                loan.days_remaining_cached = loan._compute_days_remaining(holidays)
                due_loans.append(loan)
        return Response(DueLoanSerializer(due_loans, many=True, context={'holidays': holidays}).data)


class BatchPaymentAPIView(APIView):
    @transaction.atomic
    def post(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        payments = request.data.get('payments', [])
        if not payments:
            return Response({'error': 'No payments provided.'}, status=400)

        today = date.today()
        now_time = timezone.now()
        results = []
        total_amount = Decimal('0')

        for item in payments:
            loan_id = item.get('loan_id')
            try:
                amount = Decimal(str(item.get('amount', 0)))
                if amount <= 0:
                    raise ValueError()
            except Exception:
                results.append({'loan_id': loan_id, 'status': 'error', 'message': 'Invalid amount.'})
                continue

            try:
                loan = Loan.objects.select_for_update().select_related('customer').get(
                    id=loan_id, customer__agent=agent_profile, status='active'
                )
            except Loan.DoesNotExist:
                results.append({'loan_id': loan_id, 'status': 'error', 'message': 'Loan not found.'})
                continue

            if loan.last_payment_at and (now_time - loan.last_payment_at) < timedelta(minutes=10):
                results.append({
                    'loan_id': loan_id, 'status': 'skipped',
                    'message': 'Cooldown active', 'customer': loan.customer.name,
                })
                continue

            is_first_today = not Repayment.objects.filter(loan=loan, date=today).exists()
            Repayment.objects.create(loan=loan, date=today, amount_paid=amount, recorded_by=agent_profile)
            loan.total_paid += amount
            loan.last_payment_at = now_time
            loan.last_paid_date = today
            if is_first_today:
                loan.days_paid += 1

            if loan.remaining_balance <= 0:
                loan.status = 'completed'
                lower, upper, blacklist = evaluate_customer_loan_range(loan)
                customer = loan.customer
                customer.credit_score = upper
                if blacklist:
                    customer.blacklisted = True
                customer.save()

            loan.save()
            total_amount += amount
            results.append({
                'loan_id': loan_id, 'status': 'ok', 'amount': str(amount),
                'customer': loan.customer.name, 'remaining_balance': str(loan.remaining_balance),
            })

        agent_profile.amount_in_hand += total_amount
        agent_profile.save(update_fields=['amount_in_hand'])
        cache.delete(f'agent_dashboard_{request.user.id}')

        return Response({
            'results': results,
            'total_amount': str(total_amount),
        })


# ---------------------------------------------------------------------------
# Agent — Loan calculator
# ---------------------------------------------------------------------------

class LoanCalculatorAPIView(APIView):
    permission_classes = []

    def post(self, request):
        mode = request.data.get('mode', 'forward')
        try:
            interest = float(request.data.get('interest', 20))
            days = int(request.data.get('days', 20))
            if mode == 'forward':
                amount = float(request.data.get('amount'))
                total_due = round(amount + amount * interest / 100, 2)
                daily = round(total_due / days, 2)
                return Response({'mode': mode, 'amount': amount, 'total_due': total_due, 'daily_payment': daily})
            else:
                daily = float(request.data.get('daily_payment'))
                total_due = round(daily * days, 2)
                amount = round(total_due / (1 + interest / 100), 2)
                return Response({'mode': mode, 'daily_payment': daily, 'total_due': total_due, 'amount': amount})
        except Exception:
            return Response({'error': 'Invalid parameters.'}, status=400)


# ---------------------------------------------------------------------------
# Agent — Send money to admin
# ---------------------------------------------------------------------------

class AgentSendToAdminAPIView(APIView):
    def post(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        try:
            amount = Decimal(str(request.data.get('amount')))
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=400)
        if amount <= 0 or amount > agent_profile.amount_in_hand:
            return Response({'error': 'Invalid amount or insufficient funds.'}, status=400)

        req = AdminTransactionRequest.objects.create(
            agent=agent_profile,
            requested_amount=amount,
            transaction_type='send_to_admin',
        )
        AdminNotification.create_withdrawal_notice(agent_profile.user, amount)
        return Response(AdminTransactionRequestSerializer(req).data, status=201)


# ---------------------------------------------------------------------------
# Admin — Dashboard
# ---------------------------------------------------------------------------

class AdminDashboardAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        finance = CompanyFinance.get_balance()
        notifications = AdminNotification.active_for_user(request.user)
        pending = AdminTransactionRequest.objects.filter(status='pending').select_related('agent__user')
        settings = LoanSettings.objects.first()

        return Response({
            'stats': {
                'total_customers': Customer.objects.count(),
                'total_loans': Loan.objects.count(),
                'active_loans': Loan.objects.filter(status='active').count(),
                'company_balance': str(finance.total_amount),
            },
            'loan_settings': LoanSettingsSerializer(settings).data if settings else None,
            'pending_requests': AdminTransactionRequestSerializer(pending, many=True).data,
            'notifications': AdminNotificationSerializer(notifications, many=True).data,
        })


# ---------------------------------------------------------------------------
# Admin — Customers
# ---------------------------------------------------------------------------

class AdminCustomerListAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        customers = Customer.objects.select_related('agent__user').order_by('name')
        return Response(CustomerSerializer(customers, many=True).data)


class AdminCustomerDetailAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        loans = Loan.objects.filter(customer=customer).order_by('-created_at')
        return Response({
            'customer': CustomerSerializer(customer).data,
            'loans': LoanSerializer(loans, many=True).data,
        })

    def patch(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        for field in ['name', 'phone', 'location', 'national_id', 'blacklisted', 'has_active_loan']:
            if field in request.data:
                setattr(customer, field, request.data[field])
        if 'credit_score' in request.data:
            try:
                customer.credit_score = int(request.data['credit_score'])
            except (TypeError, ValueError):
                return Response({'error': 'Invalid credit score.'}, status=400)
        if 'agent_id' in request.data:
            customer.agent = get_object_or_404(AgentProfile, id=request.data['agent_id'])
        customer.save()
        return Response(CustomerSerializer(customer).data)


class AdjustCustomerCreditAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        try:
            customer.credit_score = int(request.data.get('credit_score'))
            customer.save()
        except Exception:
            return Response({'error': 'Invalid credit score.'}, status=400)
        return Response(CustomerSerializer(customer).data)


# ---------------------------------------------------------------------------
# Admin — Loan settings
# ---------------------------------------------------------------------------

class UpdateLoanSettingsAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request):
        settings = LoanSettings.objects.first()
        if not settings:
            return Response({'error': 'No loan settings found.'}, status=404)
        for field in ['interest_percent', 'duration_days', 'min_loan_amount', 'max_loan_amount']:
            if field in request.data:
                setattr(settings, field, request.data[field])
        settings.save()
        return Response(LoanSettingsSerializer(settings).data)


# ---------------------------------------------------------------------------
# Admin — Agents
# ---------------------------------------------------------------------------

class AdminAgentsAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        agents = AgentProfile.objects.select_related('user').all()
        return Response(AgentProfileSerializer(agents, many=True).data)


class GenerateAgentInviteAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request):
        token = RegistrationToken.create_token(hours_valid=2)
        url = request.build_absolute_uri(f'/accounts/register/?token={token.token}')
        return Response({'url': url, 'expires_at': token.expires_at})


class EditAgentAPIView(APIView):
    permission_classes = [IsStaff]

    def patch(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        if 'username' in request.data:
            agent.user.username = request.data['username']
        if 'email' in request.data:
            agent.user.email = request.data['email']
        agent.user.save()
        return Response(AgentProfileSerializer(agent).data)


class AgentDetailAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, agent_id):
        from django.db.models import F
        agent = get_object_or_404(AgentProfile, id=agent_id)
        loans = Loan.objects.filter(customer__agent=agent)
        total_loans = loans.count()
        completed_loans = loans.filter(status='completed').count()
        active_loans_count = loans.filter(status='active').count()

        balance_agg = loans.filter(status='active').aggregate(
            total_loaned=Sum('principal_amount'),
            total_balance=Sum(F('total_due') - F('total_paid')),
        )
        total_active_amount_loaned = balance_agg['total_loaned'] or 0
        total_active_balance = max(balance_agg['total_balance'] or 0, 0)

        holidays = get_holidays()
        active_loans_qs = list(loans.filter(status='active').select_related('customer'))
        default_loans = sum(
            1 for loan in active_loans_qs
            if (loan._compute_days_elapsed(holidays) - loan.days_paid) >= 3
        )

        def pct(count):
            return round((count / total_loans) * 100, 1) if total_loans > 0 else 0

        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        weekly_performance = AgentDailyPerformance.objects.filter(
            agent=agent, date__gte=week_start, date__lte=today
        ).order_by('date')
        weekly_totals = weekly_performance.aggregate(
            total_gross=Sum('gross_interest'),
            total_withdrawn=Sum('total_withdrawn'),
            total_net=Sum('net'),
        )
        recent_transactions = AgentTransactionLog.objects.filter(
            agent=agent
        ).select_related('approved_by').order_by('-approved_at')[:4]

        return Response({
            'agent': AgentProfileSerializer(agent).data,
            'total_loans': total_loans,
            'completed_loans': completed_loans,
            'completed_pct': pct(completed_loans),
            'active_loans_count': active_loans_count,
            'active_pct': pct(active_loans_count),
            'default_loans': default_loans,
            'default_pct': round((default_loans / active_loans_count * 100), 1) if active_loans_count > 0 else 0,
            'total_active_balance': float(total_active_balance),
            'total_active_amount_loaned': float(total_active_amount_loaned),
            'weekly_performance': AgentDailyPerformanceSerializer(weekly_performance, many=True).data,
            'weekly_totals': {
                'total_gross': float(weekly_totals['total_gross'] or 0),
                'total_withdrawn': float(weekly_totals['total_withdrawn'] or 0),
                'total_net': float(weekly_totals['total_net'] or 0),
            },
            'recent_transactions': AgentTransactionLogSerializer(recent_transactions, many=True).data,
            'stats': {
                'total_customers': Customer.objects.filter(agent=agent).count(),
                'active_loans_count': active_loans_count,
                'total_loans': total_loans,
            },
        })


class AgentTransactionLogAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        logs = AgentTransactionLog.objects.filter(agent=agent).order_by('-approved_at')
        return Response(AgentTransactionLogSerializer(logs, many=True).data)


class AgentPerformanceHistoryAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        period = request.query_params.get('period', 'week')
        qs = AgentDailyPerformance.objects.filter(agent=agent).order_by('-date')
        if period == 'week':
            qs = qs[:7]
        elif period == 'month':
            qs = qs[:30]
        return Response(AgentDailyPerformanceSerializer(qs, many=True).data)


class AdminGiveAgentMoneyAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        try:
            amount = Decimal(str(request.data.get('amount')))
            if amount <= 0:
                raise ValueError()
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=400)

        with transaction.atomic():
            finance = CompanyFinance.get_balance()
            if amount > finance.total_amount:
                return Response({'error': 'Insufficient company funds.'}, status=400)
            finance.total_amount -= amount
            finance.save()
            agent.amount_in_hand += amount
            agent.save(update_fields=['amount_in_hand'])

            FinanceTransaction.objects.create(
                admin=request.user,
                transaction_type="withdraw",
                amount=amount,
                note=f"Given to agent {agent.user.username}"
            )

        return Response({'ok': True, 'agent_balance': str(agent.amount_in_hand)})


class AdminApproveTransactionAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request, request_id):
        req = get_object_or_404(AdminTransactionRequest, id=request_id)
        action = request.data.get('action')  # 'approve' or 'reject'
        if action == 'approve':
            actual = Decimal(str(request.data.get('actual_received_amount', req.requested_amount)))
            with transaction.atomic():
                req.status = 'approved'
                req.actual_received_amount = actual
                req.save()

                if req.transaction_type == 'send_to_admin':
                    finance = CompanyFinance.get_balance()
                    finance.total_amount += actual
                    finance.save()

                    FinanceTransaction.objects.create(
                        admin=request.user,
                        transaction_type="deposit",
                        amount=actual,
                        note=f"Sent to admin By {req.agent.user.username}. Balance {finance.total_amount} SZL"
                    )

                req.agent.amount_in_hand -= actual
                req.agent.save(update_fields=['amount_in_hand'])

                AgentTransactionLog.objects.create(
                    agent=req.agent,
                    approved_by=request.user,
                    transaction_request=req,
                    transaction_type=req.transaction_type,
                    requested_amount=req.requested_amount,
                    actual_amount=actual,
                    note=f"{req.get_transaction_type_display()} approved by {request.user.username}",
                )

                # --- Daily performance snapshot ---
                agent = req.agent
                today = timezone.localdate()

                loans_today = Loan.objects.filter(
                    customer__agent=agent,
                    created_at__date=today,
                ).values('principal_amount', 'interest_rate')

                gross_interest = sum(
                    l['principal_amount'] * l['interest_rate'] / Decimal('100')
                    for l in loans_today
                )

                total_withdrawn = AgentTransactionLog.objects.filter(
                    agent=agent,
                    approved_at__date=today,
                    transaction_type__in=['withdraw', 'send_to_admin'],
                ).aggregate(total=Sum('actual_amount'))['total'] or Decimal('0')

                active_loans = Loan.objects.filter(customer__agent=agent, status='active')
                total_due = active_loans.count()
                collected = active_loans.filter(
                    repayment__date=today
                ).distinct().count()
                collection_pct = round((collected / total_due) * 100, 2) if total_due else 0

                AgentDailyPerformance.objects.update_or_create(
                    agent=agent,
                    date=today,
                    defaults=dict(
                        gross_interest=gross_interest,
                        total_withdrawn=total_withdrawn,
                        net=gross_interest - total_withdrawn,
                        loans_collected=collected,
                        total_due_loans=total_due,
                        collection_percentage=collection_pct,
                    ),
                )
        elif action == 'reject':
            req.status = 'rejected'
            req.rejection_note = request.data.get('rejection_note', '')
            req.save()
        else:
            return Response({'error': 'action must be approve or reject.'}, status=400)

        return Response(AdminTransactionRequestSerializer(req).data)


# ---------------------------------------------------------------------------
# Admin — Finance
# ---------------------------------------------------------------------------

class AdminFinanceDashboardAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        finance = CompanyFinance.get_balance()
        transactions = FinanceTransaction.objects.order_by('-timestamp')[:50]
        return Response({
            'balance': str(finance.total_amount),
            'transactions': FinanceTransactionSerializer(transactions, many=True).data,
        })


class DepositAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request):
        try:
            amount = Decimal(str(request.data.get('amount')))
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=400)
        note = request.data.get('note', '')
        with transaction.atomic():
            finance = CompanyFinance.get_balance()
            finance.total_amount += amount
            finance.save()
            FinanceTransaction.objects.create(
                admin=request.user, transaction_type='deposit', amount=amount, note=note
            )
        return Response({'balance': str(finance.total_amount)})


class WithdrawAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request):
        try:
            amount = Decimal(str(request.data.get('amount')))
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=400)
        note = request.data.get('note', '')
        with transaction.atomic():
            finance = CompanyFinance.get_balance()
            if amount > finance.total_amount:
                return Response({'error': 'Insufficient funds.'}, status=400)
            finance.total_amount -= amount
            finance.save()
            FinanceTransaction.objects.create(
                admin=request.user, transaction_type='withdraw', amount=amount, note=note
            )
        return Response({'balance': str(finance.total_amount)})


class DismissNotificationAPIView(APIView):
    permission_classes = [IsStaff]

    def post(self, request, pk):
        notif = get_object_or_404(AdminNotification, pk=pk)
        notif.dismissed_by.add(request.user)
        return Response({'ok': True})


# ---------------------------------------------------------------------------
# Admin — Agent loans list / delete
# ---------------------------------------------------------------------------

class AgentLoanListAPIView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, agent_id, loan_status):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        if loan_status == 'default':
            holidays = get_holidays()
            loans = Loan.objects.filter(customer__agent=agent, status='active').select_related('customer')
            loans = [loan for loan in loans if loan.days_missed >= 3]
        else:
            loans = Loan.objects.filter(customer__agent=agent, status=loan_status).select_related('customer')
        return Response(LoanSerializer(loans, many=True).data)


class DeleteLoanAPIView(APIView):
    permission_classes = [IsStaff]

    def delete(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)
        with transaction.atomic():
            if loan.days_missed <= 0:
                agent = loan.customer.agent
                agent.amount_in_hand += loan.principal_amount
                agent.save(update_fields=['amount_in_hand'])
            loan.delete()
        return Response({'ok': True})


class AgentWithdrawRequestAPIView(APIView):
    def post(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        if agent.user != request.user and not is_staff(request.user):
            return Response({'error': 'Unauthorized.'}, status=403)
        try:
            amount = Decimal(str(request.data.get('amount')))
            if amount <= 0:
                raise ValueError()
        except Exception:
            return Response({'error': 'Invalid amount.'}, status=400)
        if amount > agent.amount_in_hand:
            return Response({'error': 'Insufficient balance.'}, status=400)
        note = request.data.get('note', '')
        req = AdminTransactionRequest.objects.create(
            agent=agent, requested_amount=amount, transaction_type='withdraw',
            rejection_note=note,
        )
        AdminNotification.create_withdrawal_notice(agent.user, amount)
        return Response(AdminTransactionRequestSerializer(req).data, status=201)
