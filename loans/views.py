from django.views import View
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from datetime import date
from httpx import request
import json
import loans
from .models import CompanyFinance, FinanceTransaction,AdminNotification
from .models import Customer, Loan, Repayment
from .utils import agent_performance
from accounts.models import AgentProfile

from django.shortcuts import get_object_or_404, render
from django.views import View
from django.db.models import Sum, Q, Exists, OuterRef, Count
from datetime import date
from django.db.models.functions import Lower
from django.core.cache import cache
from django.utils import timezone

LOAN_LADDER_20 = [250, 500, 1000, 1500, 2000, 2500, 3000, 3500]
LOAN_LADDER_25 = [400, 500, 600, 1000, 1500, 2000, 2500, 3000, 3500]




from datetime import timedelta

def working_days_between(start, end):
    days = 0
    current = start
    while current < end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days

def evaluate_customer_loan_range(previous_loan):

    if not previous_loan:
        return 200, 500, False

    days_missed = previous_loan.days_missed
    total_working_days = working_days_between(
        previous_loan.start_date,
        date.today()
    )

    current_amount = previous_loan.principal_amount

    # Determine ladder + expected duration
    if previous_loan.interest_rate == 20:
        ladder = LOAN_LADDER_20
        expected_days = 20
        late_cutoff = 25
    else:
        ladder = LOAN_LADDER_25
        expected_days = 25
        late_cutoff = 30

    # Find current index
    try:
        index = ladder.index(current_amount)
    except ValueError:
        return ladder[0], ladder[-1], False

    # 🧠 RELAXED BLACKLIST LOGIC
    # Only blacklist extreme defaulters
    if days_missed > 12 and total_working_days > late_cutoff + 5:
        return 0, 0, True
        

    # 🔴 HIGH RISK → STRONG DOWNGRADE (instead of blacklist)
    if days_missed > 7 and total_working_days > late_cutoff:
        new_index = max(index - 3, 0)

    # 🟢 VERY GOOD
    elif total_working_days < 10 and days_missed <= 1:
        new_index = min(index + 2, len(ladder) - 1)

    # 🟢 GOOD (with buffer)
    elif total_working_days <= expected_days + 3 and days_missed <= 2:
        new_index = min(index + 1, len(ladder) - 1)

    # 🟡 AVERAGE
    elif days_missed <= 5:
        new_index = index

    # 🔴 BAD
    else:
        new_index = max(index - 2, 0)

    lower = ladder[0]
    upper = ladder[new_index]

    return lower, upper, False

class AgentDashboardView(View):
    template_name = "loans/agent_dashboard.html"

    def get(self, request, *args, **kwargs):
        agent_id = request.user.id
        cache_key = f"agent_dashboard_{agent_id}"

        name_query = request.GET.get("name", "").strip()
        phone_query = request.GET.get("phone", "").strip()

        context = cache.get(cache_key)

        if not context:
            from .models import get_holidays
            agent_profile = get_object_or_404(AgentProfile, user=request.user)
            today = timezone.localdate()

            # Single query: all active loans with today's payment amount annotated
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
                    )
                )
                .order_by(Lower("customer__name"))
            )

            # Compute days_remaining for every loan with a single holidays fetch
            holidays = get_holidays()
            for loan in active_loans:
                loan.days_remaining_cached = loan._compute_days_remaining(holidays)

            due_loans = [loan for loan in active_loans if not loan.paid_today]

            amount_to_collect = sum(loan.daily_payment for loan in active_loans)
            
            amount_collected = Repayment.objects.filter(
                loan__customer__agent=agent_profile,
                date=today
                    ).aggregate(total=Sum('amount_paid'))['total'] or 0
            loans_collected_count = Repayment.objects.filter(
                        loan__customer__agent=agent_profile,
                        date=today
                    ).values('loan').distinct().count()

            completed_today = Loan.objects.filter(
                customer__agent=agent_profile,
                status='completed',
                repayment__date=today
            ).distinct().count()
            total_due_loans = len(active_loans) + completed_today

            loan_collection_percentage = round(
                (loans_collected_count / total_due_loans) * 100, 2
            ) if total_due_loans else 0
            amount_collection_percentage = round(
                (amount_collected / amount_to_collect) * 100, 2
            ) if amount_to_collect else 0
            performance = round((loans_collected_count / total_due_loans) * 100, 2) if total_due_loans else 0

            # Loans paid today (for the collapsible table)
            loans_paid_today = [loan for loan in active_loans if loan.paid_today]

            # Loans taken today
            loans_taken_today = list(
                Loan.objects.filter(customer__agent=agent_profile, created_at__date=today)
                .select_related('customer')
                .order_by(Lower("customer__name"))
            )

            context = {
                "agent": agent_profile,
                "amount_in_hand": agent_profile.amount_in_hand,
                "loans": loans_paid_today,
                "due_loans": due_loans,
                "performance": performance,
                "loans_taken_today": loans_taken_today,
                "amount_to_collect": amount_to_collect,
                "amount_collected": amount_collected,
                "amount_collection_percentage": amount_collection_percentage,
                "loans_collected_count": loans_collected_count,
                "total_due_loans": total_due_loans,
                "loan_collection_percentage": loan_collection_percentage,
                "total_customers": Customer.objects.filter(agent=agent_profile).count(),
            }
            # Cache for 2 minutes — signals will invalidate on payment events
            cache.set(cache_key, context, timeout=120)

        # Customer search is always live (never cached)
        customers = None
        searched = False
        if name_query or phone_query:
            searched = True
            agent_profile = context["agent"]
            customers = (
                Customer.objects
                .filter(agent=agent_profile)
                .annotate(total_loans=Count('loan'))
            )
            if name_query:
                customers = customers.filter(name__icontains=name_query)
            if phone_query:
                customers = customers.filter(phone__icontains=phone_query)

        context["customers"] = customers
        context["searched"] = searched

        return render(request, self.template_name, context)
        
from decimal import Decimal

class MarkPaymentView(LoginRequiredMixin, View):
    def post(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = date.today()
        now_time = timezone.now()

        # Get amount from POST or use default daily payment
        amount = request.POST.get("amount")
        try:
            amount = Decimal(amount) if amount else loan.daily_payment
        except:
            messages.error(request, "Invalid payment amount.")
            return redirect("loans:agent_dashboard")

        # Prevent duplicate payment within 10 minutes
        if loan.last_payment_at and (now_time - loan.last_payment_at < timedelta(minutes=10)):
            messages.warning(
                request,
                "Payment already recorded. Please wait 10 minutes before trying again."
            )
            return redirect("loans:agent_dashboard")
        
        is_first_payment_today = not Repayment.objects.filter(
            loan=loan,
            date=today
        ).exists()

        # Record a new repayment (allow multiple per day)
        Repayment.objects.create(
            loan=loan,
            date=today,
            amount_paid=amount,
            recorded_by=agent_profile
        )

        # Update loan totals
        loan.total_paid += amount
        loan.last_payment_at = now_time
        loan.last_paid_date = today

        
        # Increment days_paid only if this is the first payment today
        if is_first_payment_today:
            loan.days_paid += 1

        # Update agent cash
        agent_profile.amount_in_hand += amount
        agent_profile.save()

        # Mark loan as completed if fully paid
        from django.contrib import messages

        # Mark loan as completed if fully paid
        if loan.remaining_balance <= 0:
            loan.status = "completed"
            lower, upper, blacklist_recommended = evaluate_customer_loan_range(loan)

            customer = loan.customer

            message_parts = []

            # Loan completion message
            message_parts.append(
                f"Loan #{loan.id} has been fully paid and marked as completed."
            )

            # Loan range update
            if customer.credit_score != upper:
                message_parts.append(
                    f"Customer loan eligibility updated: New maximum loan amount is {upper}."
                )

            # Blacklist logic
            if blacklist_recommended:
                if not customer.blacklisted:
                    customer.blacklisted = True
                    message_parts.append(
                        "⚠ Customer has been automatically BLACKLISTED due to payment history."
                    )
                else:
                    message_parts.append(
                        "Customer remains blacklisted."
                    )
            else:
                if customer.blacklisted:
                    message_parts.append(
                        "Customer is still manually blacklisted."
                    )
                else:
                    message_parts.append(
                        "Customer is eligible for future loans."
                    )

            # Save updates
            customer.credit_score = upper
            customer.save()

            # Final combined message
            messages.success(request, " ".join(message_parts))

        loan.save()

        messages.success(
            request,
            f"Payment of {amount} SZL recorded for {loan.customer.name}. Remaining balance: {loan.remaining_balance:.2f} SZL"
        )
        return redirect("loans:agent_dashboard")
    
from django.db import transaction
class ReversePaymentView(View):
    @transaction.atomic
    def post(self, request, loan_id):
        loan = get_object_or_404(Loan, id=loan_id)

        # Ensure agent only reverses their own loan
        agent_profile = get_object_or_404(
            AgentProfile, user=request.user
        )

        if loan.customer.agent != agent_profile:
            messages.error(request, "Unauthorized action.")
            return redirect("loans:agent_dashboard")

        today = date.today()

        # ✅ Get the LATEST payment made today
        repayment = (
            Repayment.objects
            .filter(loan=loan, date=today)
            .order_by("-id")   # latest created
            .first()
        )

        if repayment:
            amount = repayment.amount_paid
            customer_name = loan.customer.name

            # ✅ Return money back to agent
            agent_profile.amount_in_hand -= amount
            loan.total_paid -= amount
            agent_profile.save()
            loan.save()
            # ✅ Delete repayment
            
            repayment.delete()

            last_repayment = (
                Repayment.objects
                .filter(loan=loan)
                .order_by("-date", "-id")
                .first()
            )

            if last_repayment:
                loan.last_paid_date = last_repayment.date
                loan.last_payment_at = last_repayment.date
            else:
                loan.last_paid_date = None
                loan.last_payment_at = None

            loan.save()

            # ✅ Clear dashboard cache
            cache.delete(f"agent_dashboard_{request.user.id}")

            messages.success(
                request,
                f"Reversed latest payment of SZL {amount} for {customer_name}."
            )
        else:
            messages.warning(
                request,
                f"No payment made today for {loan.customer.name} to reverse."
            )

        return redirect("loans:agent_dashboard")
       
# loans/views.py
from django.views.generic import ListView
from .models import Customer,LoanSettings
from .forms import CustomerForm, LoanForm

class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = "loans/customer_list.html"
    context_object_name = "customers"

    def get_queryset(self):
        agent_profile = get_object_or_404(AgentProfile, user=self.request.user)
        cache_key = f"customer_list_{agent_profile.id}"
        customers = cache.get(cache_key)
        if not customers:
            customers = list(
                Customer.objects.filter(agent=agent_profile)
                .annotate(total_loans=Count('loan'))
                .order_by('name')
            )
            cache.set(cache_key, customers, timeout=300)
        return customers
    

class CreateCustomerAndLoanView(View):
    template_name = "loans/create_customer_loan.html"

    def get(self, request):
        customer_form = CustomerForm()
        return render(request, self.template_name, {
            'customer_form': customer_form,
        })

    def post(self, request):
        customer_form = CustomerForm(request.POST)

        if customer_form.is_valid():
            # Create customer object but don’t save yet
            customer = customer_form.save(commit=False)

            # Attach the agent to the new customer
            agent_profile = AgentProfile.objects.get(user=request.user)
            customer.agent = agent_profile
                # Credit system fields
            settings = LoanSettings.objects.first()
            upperSettings = settings.max_loan_amount if settings else 500
            customer.credit_score = upperSettings

            # Save fully now
            customer.save()

            messages.success(request, f"Customer {customer.name} created successfully.")

            # Redirect to loan qualification page for this new customer
            return redirect(f"loans:loan_qualification", customer.id)

        # Invalid form — re-render page with errors
        messages.error(request, "Please correct the errors below.")
        return render(request, self.template_name, {
            'customer_form': customer_form,
        })


class AddLoanExistingCustomerView(View):
    template_name = "loans/add_loan_existing.html"

    def get(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        loan_form = LoanForm()
        # Filter only customers of this agent
        loan_form.fields['customer'].queryset = Customer.objects.filter(agent=agent_profile)
        return render(request, self.template_name, {'loan_form': loan_form})

    def post(self, request):
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        loan_form = LoanForm(request.POST)
        loan_form.fields['customer'].queryset = Customer.objects.filter(agent=agent_profile)

        if loan_form.is_valid():
            loan = loan_form.save()
            messages.success(request, f"Loan for customer '{loan.customer.name}' added successfully!")
            return redirect('loans:customer_list')
        else:
            return render(request, self.template_name, {'loan_form': loan_form})


class LoanQualificationView(View):
    template_name = "loans/loan_qualification.html"

    def get(self, request, customer_id=None):
        """
        Show loan qualification page.
        If customer_id is provided, use the existing customer.
        If no customer_id, treat as a new customer and show default ranges.
        """
        if customer_id:
            # Existing customer
            customer = get_object_or_404(Customer, id=customer_id)

            if customer.blacklisted:
                messages.error(request, f"{customer.name} is blacklisted and cannot apply.")
                return redirect('loans:agent_dashboard')

            settings = LoanSettings.objects.first()

            upper = customer.credit_score
            lower = settings.min_loan_amount if settings else 200

            
        else:
            # New customer
            customer = None
            # Default ranges from LoanSettings (or any defaults you want)
            settings = LoanSettings.objects.first()
            lower = settings.min_loan_amount if settings else 200
            upper = settings.max_loan_amount if settings else 500
    

        context = {
            'customer': customer,
            'lower': lower,
            'upper': upper,
        }
        return render(request, self.template_name, context)


# loans/views.py
from decimal import Decimal

class LoanOfferView(View):
    template_name = "loans/loan_offer.html"

    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)

        # Default amount for new customer or passed via query param
        amount = request.GET.get("amount", 250)
        try:
            amount = float(amount)
        except ValueError:
            amount = 200

        offers = [
            {"interest": 20, "days": 40},
        ]

        # Calculate repayment details
        for offer in offers:
            total_due = amount + (amount * offer["interest"] / 100)
            offer["total_due"] = round(total_due, 2)
            offer["daily_payment"] = round(total_due / offer["days"], 2)

        return render(request, self.template_name, {
            "customer": customer,
            "amount": amount,
            "offers": offers,
        })

    from decimal import Decimal
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    from django.db import transaction

    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        agent_profile = AgentProfile.objects.get(user=request.user)

        interest = Decimal(request.POST.get("interest"))
        days = int(request.POST.get("days"))
        amount = Decimal(request.POST.get("amount"))

        # Map 40 working days back to 20 for database entry mapping
        if days == 40:
            days = 20

        # 🔒 1. CHECK FOR ACTIVE LOAN
        has_active_loan = Loan.objects.filter(
            customer=customer,
            status="active"
        ).exists()

        if has_active_loan:
            messages.warning(
                request,
                f"{customer.name} already has an active loan. They must pay it first."
            )
            return redirect("loans:agent_dashboard")

        total_due = amount + (amount * interest / Decimal("100"))
        daily_payment = total_due / days

        # 🔒 2. CHECK AGENT CASH
        if amount > agent_profile.amount_in_hand:
            messages.warning(
                request,
                f"Amount is more than what agent has ({agent_profile.amount_in_hand} SZL). Request amount from Admin."
            )
            return redirect("loans:agent_dashboard")

        # ✅ 3. CREATE LOAN (ATOMIC)
        with transaction.atomic():
            Loan.objects.create(
                customer=customer,
                principal_amount=amount,
                interest_rate=interest,
                duration_days=days,
                total_due=total_due.quantize(Decimal("0.01")),
                daily_payment=daily_payment.quantize(Decimal("0.01")),
                status="active"
            )

            agent_profile.amount_in_hand -= amount
            agent_profile.save(update_fields=["amount_in_hand"])

        messages.success(
            request,
            f"Loan created successfully for {customer.name} "
            f"({amount} SZL at {interest}% for {days} days)."
        )
        return redirect("loans:agent_dashboard")

from datetime import timedelta
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View
from .models import Customer, Loan, Repayment

from loans.models import Customer, Loan, Repayment, PublicHoliday




from django.shortcuts import render, get_object_or_404
from django.views import View
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum

from loans.models import Customer, Loan, Repayment, PublicHoliday


class CustomerHistoryView(View):
    template_name = "loans/customer_history.html"

    def get(self, request, customer_id, loan_id=None):
        customer = get_object_or_404(Customer, id=customer_id)
        today = timezone.now().date()

        if loan_id:
            loan = get_object_or_404(Loan, id=loan_id, customer=customer)
        else:
            loan = Loan.objects.filter(customer=customer).order_by('-start_date').first()
        history = []

        if loan:
            repayments = Repayment.objects.filter(loan=loan).order_by('date', 'id')

            # Group payments by date
            payments_by_date = {}
            for r in repayments:
                payments_by_date.setdefault(r.date, []).append(r.amount_paid)

            # ✅ TOTAL PAID
            total_paid = repayments.aggregate(total=Sum('amount_paid'))['total'] or 0

            # ✅ TOTAL REQUIRED (principal + interest)
            total_required = loan.principal_amount + (
                loan.principal_amount * loan.interest_rate / 100
            )

            # ✅ LAST PAYMENT DATE
            last_payment_date = repayments.last().date if repayments.exists() else None

            # ✅ Determine if loan is closed
            is_loan_closed = total_paid >= total_required

            # ✅ END DATE LOGIC (FIXED)
            if is_loan_closed and last_payment_date:
                end_date = last_payment_date
            else:
                end_date = today

            holidays = set(PublicHoliday.objects.values_list("holiday_date", flat=True))

            current_day = loan.start_date

            history.append({
                    "date": loan.created_at.date(),
                    "type": "disbursed",
                    "label": f"Loan disbursed – E{loan.principal_amount:.2f}",
                })

            while current_day <= end_date:
                # Skip weekends
                if current_day.weekday() >= 5:
                    current_day += timedelta(days=1)
                    continue

                # Skip holidays
                if current_day in holidays:
                    current_day += timedelta(days=1)
                    continue

            

                if current_day in payments_by_date:
                    payments = payments_by_date[current_day]
                    total_day_payment = sum(payments)
                    breakdown = ", ".join(f"E{p:.2f}" for p in payments)

                    history.append({
                        "date": current_day,
                        "type": "paid",
                        "label": f"Payment received – E{total_day_payment:.2f} ------------------ [{breakdown}]",
                    })

                else:
                    history.append({
                        "date": current_day,
                        "type": "missed",
                        "label": "Missed payment",
                    })

                current_day += timedelta(days=1)

        context = {
            "customer": customer,
            "loan": loan,
            "history": history,
        }

        return render(request, self.template_name, context)
    

from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.contrib.auth.mixins import UserPassesTestMixin
from datetime import date, timedelta
from django.db.models import Sum, Count
from .models import AgentProfile, Customer, Loan, Repayment, LoanSettings,AdminTransactionRequest
from decimal import Decimal

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff

    def handle_no_permission(self):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You do not have permission to access this page.")


class AdminDashboardView(AdminRequiredMixin, View):
    def get(self, request):
        cache_key = "admin_dashboard"
        context = cache.get(cache_key)

        if not context:
            finance = CompanyFinance.get_balance()
            notifications = AdminNotification.active_for_user(request.user)
            total_customers = Customer.objects.count()
            total_loans = Loan.objects.count()
            active_loans = Loan.objects.filter(status="active").count()
            settings = LoanSettings.objects.first()
            pending_requests = AdminTransactionRequest.objects.filter(status='pending').select_related('agent__user')

            context = {
                "total_customers": total_customers,
                "total_loans": total_loans,
                "active_loans": active_loans,
                "loan_settings": settings,
                "pending_requests": pending_requests,
                "finance": finance,
                "notifications": notifications,
            }
            cache.set(cache_key, context)

        return render(request, "loans/admin_dashboard.html", context)
    
class AdjustCustomerCreditView(AdminRequiredMixin, View):
    """Admin can adjust a customer's credit score"""

    def post(self, request, customer_id):
        customer = get_object_or_404(Customer, id=customer_id)
        new_credit = request.POST.get("credit_score")
        try:
            new_credit = int(new_credit)
            customer.credit_score = new_credit
            customer.save()
            # Optional: add messages framework for success
        except:
            pass
        return redirect("loans:admin_dashboard")


class UpdateLoanSettingsView(AdminRequiredMixin, View):
    """Admin can update only provided loan setting fields."""

    def post(self, request):
        settings = LoanSettings.objects.first()
        if not settings:
            # If no settings exist yet, create one
            settings = LoanSettings.objects.create()

        # Get values from form safely
        interest = request.POST.get("interest_percent")
        duration = request.POST.get("duration_days")
        min_amount = request.POST.get("min_loan_amount")
        max_amount = request.POST.get("max_loan_amount")

        # Update only fields that have a value
        if interest:
            try:
                settings.interest_percent = Decimal(interest)
            except:
                pass

        if duration:
            try:
                settings.duration_days = int(duration)
            except:
                pass

        if min_amount:
            try:
                settings.min_loan_amount = Decimal(min_amount)
            except:
                pass

        if max_amount:
            try:
                settings.max_loan_amount = Decimal(max_amount)
            except:
                pass

        settings.save()
        return redirect("loans:admin_dashboard")

class AdminCustomerListView(AdminRequiredMixin, View):
    template_name = "loans/admin_customers.html"

    def get(self, request):
        customers = Customer.objects.select_related("agent").all()
        return render(request, self.template_name, {"customers": customers})
    
from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

class AdminCustomerEditView(AdminRequiredMixin, View):
    template_name = "loans/admin_edit_customer.html"

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        agents = AgentProfile.objects.all()

        context = {
            "customer": customer,
            "agents": agents,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)

        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        location = request.POST.get("location", "").strip()
        national_id = request.POST.get("national_id", "").strip()
        credit_score = request.POST.get("credit_score", "").strip()
        agent_id = request.POST.get("agent", "").strip()

        # =========================
        # Basic Field Updates
        # =========================
        if name:
            customer.name = name

        if phone:
            customer.phone = phone

        if location:
            customer.location = location

        if national_id:
            customer.national_id = national_id

        # =========================
        # Credit Score Validation
        # =========================
        if credit_score:
            try:
                customer.credit_score = int(credit_score)
            except ValueError:
                messages.warning(request, "Credit score must be a valid number.")

        # =========================
        # Agent Reassignment
        # =========================
        if agent_id:
            try:
                agent = AgentProfile.objects.get(id=agent_id)
                customer.agent = agent
            except AgentProfile.DoesNotExist:
                messages.warning(request, "Invalid agent selected.")

        # =========================
        # Active Loan Toggle
        # =========================
        customer.has_active_loan = request.POST.get("has_active_loan") == "on"

        # =========================
        # 🔴 Admin Blacklist Toggle
        # =========================
        previous_status = customer.blacklisted
        new_status = request.POST.get("blacklisted") == "on"

        customer.blacklisted = new_status


        # =========================
        # Save
        # =========================
        customer.save()

        # Status-specific message
        if new_status and not previous_status:
            messages.success(request, f"{customer.name} has been blacklisted.")
        elif not new_status and previous_status:
            messages.success(request, f"{customer.name} has been removed from blacklist.")
        else:
            messages.success(request, f"{customer.name}'s details updated successfully.")

        return redirect("loans:admin_customers")
     
import secrets
from django.urls import reverse
from accounts.models import AgentProfile,RegistrationToken

class AdminAgentsView(AdminRequiredMixin, View):
    """Admin can manage agents: view, edit, and generate invite links"""
    template_name = "loans/admin_agents.html"

    def get(self, request):
        agents = AgentProfile.objects.select_related("user").all()
        return render(request, self.template_name, {"agents": agents})

from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

@method_decorator(login_required, name='dispatch')
class GenerateAgentInviteView(View):
    """Admin/staff-only view to generate agent registration links (valid for 2 hours)"""

    def generate_link(self, request):
        token = RegistrationToken.create_token(hours_valid=2)
        registration_url = request.build_absolute_uri(f"/accounts/register/?token={token.token}")
        return registration_url, token.expires_at

    def dispatch(self, request, *args, **kwargs):
        # Check permissions for all HTTP methods
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        url, expires = self.generate_link(request)
        return render(request, "accounts/admin_link.html", {"registration_url": url, "expires": expires})

    def post(self, request, *args, **kwargs):
        # same logic as GET, allows a POST button if desired
        url, expires = self.generate_link(request)
        return render(request, "accounts/admin_link.html", {"registration_url": url, "expires": expires})

class EditAgentView(View):
    """Admin can edit agent details"""

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        return render(request, "loans/edit_agent.html", {"agent": agent})

    def post(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        user = agent.user

        # Only update if field is provided and non-empty
        first_name = request.POST.get("first_name")
        if first_name:
            user.first_name = first_name

        last_name = request.POST.get("last_name")
        if last_name:
            user.last_name = last_name

        email = request.POST.get("email")
        if email:
            user.email = email

        user.save()
        messages.success(request, "Agent details updated successfully!")
        return redirect("loans:admin_agents")

class SendToAdminRequestView(View):
    def get(self, request):
        return render(request, "loans/send_to_admin.html")

    def post(self, request):
        agent = AgentProfile.objects.get(user=request.user)
        requested_amount = Decimal(request.POST.get("amount"))

        if requested_amount > agent.amount_in_hand:
            messages.error(request, "Insufficient balance")
            return redirect("loans:agent_dashboard")

        AdminTransactionRequest.objects.create(
            agent=agent,
            requested_amount=requested_amount,
            transaction_type="send_to_admin"
        )

        messages.success(request, f"Request to send {requested_amount} SZL submitted for admin approval.")
        return redirect("loans:agent_dashboard")
    

class AdminApproveTransactionView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff

    def post(self, request, request_id):
        transaction_request = get_object_or_404(AdminTransactionRequest, id=request_id)
        action = request.POST.get('action')
        actual_amount = request.POST.get('actual_amount')
        rejection_note = request.POST.get('rejection_note')

        if action == 'approve':
            amount = transaction_request.requested_amount
            if actual_amount:
                try:
                    amount = float(actual_amount)
                except ValueError:
                    messages.error(request, "Invalid amount entered.")
                    return redirect('loans:admin_dashboard')
            
            if transaction_request.transaction_type == 'send_to_admin':
                finance = CompanyFinance.get_balance()

                finance.total_amount += amount
                finance.save()

                FinanceTransaction.objects.create(
                    admin=request.user,
                    transaction_type="deposit",
                    amount=amount,
                    note=f"Sent to admin By {transaction_request.agent.user.username}. Balance {finance.total_amount} SZL"
                )

            # Approve and subtract
            transaction_request.status = 'approved'
            transaction_request.actual_received_amount = amount
            transaction_request.agent.amount_in_hand -= amount
            transaction_request.agent.save()
            transaction_request.save()

            # Log this approval in the agent's transaction ledger
            from .models import AgentTransactionLog, AgentDailyPerformance
            from django.utils import timezone as tz
            from django.db.models import Sum, Exists, OuterRef
            today = tz.localdate()
            agent = transaction_request.agent

            AgentTransactionLog.objects.create(
                agent=agent,
                approved_by=request.user,
                transaction_request=transaction_request,
                transaction_type=transaction_request.transaction_type,
                requested_amount=transaction_request.requested_amount,
                actual_amount=amount,
                note=f"{transaction_request.get_transaction_type_display()} approved by {request.user.username}",
            )

            # --- Daily performance snapshot ---
            # Gross: interest earned on all loans disbursed today by this agent
            from decimal import Decimal
            loans_today = Loan.objects.filter(
                customer__agent=agent,
                created_at__date=today,
            ).values('principal_amount', 'interest_rate')
            gross_interest = sum(
                l['principal_amount'] * l['interest_rate'] / Decimal('100')
                for l in loans_today
            )

            # Total withdrawals approved for this agent today (including this one).
            # Both 'withdraw' and 'send_to_admin' reduce amount_in_hand, so both count.
            total_withdrawn = AgentTransactionLog.objects.filter(
                agent=agent,
                approved_at__date=today,
                transaction_type__in=['withdraw', 'send_to_admin'],
            ).aggregate(total=Sum('actual_amount'))['total'] or Decimal('0')

            # Collection %: active loans vs paid today
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

            messages.success(request, f"Approved {agent.user.username}'s request of {amount}.")

        elif action == 'reject':
            transaction_request.status = 'rejected'
            transaction_request.rejection_note = rejection_note or "No reason provided."
            transaction_request.save()
            messages.warning(request, f"Rejected {transaction_request.agent.user.username}'s request.")

        return redirect('loans:admin_dashboard')
    
from django.db import models

from django.db.models import F
def admin_required(user):
    return user.is_staff or user.is_superuser
from django.db.models import Count

@method_decorator([login_required, user_passes_test(admin_required)], name='dispatch')
class AgentTransactionLogView(View):
    template_name = 'loans/agent_transaction_log.html'

    def get(self, request, agent_id):
        from .models import AgentTransactionLog
        agent = get_object_or_404(AgentProfile, id=agent_id)
        logs = AgentTransactionLog.objects.filter(agent=agent).select_related('approved_by', 'transaction_request')
        return render(request, self.template_name, {
            'agent': agent,
            'logs': logs,
        })


@method_decorator([login_required, user_passes_test(admin_required)], name='dispatch')
class AgentDetailView(View):
    def get(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)

        loans = Loan.objects.filter(customer__agent=agent)

        total_loans = loans.count()
        completed_loans = loans.filter(status="completed").count()
        active_loans_count = loans.filter(status="active").count()

        # Use SQL for balance aggregation instead of Python loop
        from django.db.models import F
        balance_agg = loans.filter(status="active").aggregate(
            total_loaned=models.Sum("principal_amount"),
            total_balance=models.Sum(F('total_due') - F('total_paid'))
        )
        total_active_amount_loaned = balance_agg['total_loaned'] or 0
        total_active_balance = balance_agg['total_balance'] or 0
        if total_active_balance < 0:
            total_active_balance = 0

        # days_missed still needs Python (date arithmetic), but fetch holidays once
        from loans.models import get_holidays, AgentTransactionLog, AgentDailyPerformance
        holidays = get_holidays()
        active_loans_qs = list(loans.filter(status="active"))
        default_loans = sum(
            1 for loan in active_loans_qs
            if (loan._compute_days_elapsed(holidays) - loan.days_paid) >= 3
        )

        recent_transactions = AgentTransactionLog.objects.filter(agent=agent).select_related('approved_by')[:4]

        from django.utils import timezone as tz
        from datetime import timedelta
        from django.db.models import Sum as DSum
        today = tz.localdate()
        # This week: Monday up to and including today
        week_start = today - timedelta(days=today.weekday())  # Monday
        weekly_performance = AgentDailyPerformance.objects.filter(
            agent=agent, date__gte=week_start, date__lte=today
        ).order_by('date')
        weekly_totals = weekly_performance.aggregate(
            total_gross=DSum('gross_interest'),
            total_withdrawn=DSum('total_withdrawn'),
            total_net=DSum('net'),
        )

        def percentage(count):
            return round((count / total_loans) * 100, 1) if total_loans > 0 else 0

        context = {
            "agent": agent,
            "total_loans": total_loans,
            "completed_loans": completed_loans,
            "completed_pct": percentage(completed_loans),
            "active_loans": active_loans_count,
            "active_pct": percentage(active_loans_count),
            "default_loans": default_loans,
            "default_pct": round((default_loans / active_loans_count * 100), 1) if active_loans_count > 0 else 0,
            "total_active_amount_loaned": total_active_amount_loaned,
            "total_active_balance": total_active_balance,
            "recent_transactions": recent_transactions,
            "weekly_performance": weekly_performance,
            "weekly_totals": weekly_totals,
        }

        return render(request, "loans/agent_detail.html", context)
    
@method_decorator([login_required, user_passes_test(admin_required)], name='dispatch')
class AgentPerformanceHistoryView(View):
    template_name = 'loans/agent_performance_history.html'
    PAGE_SIZE = 7  # one week per page

    def get(self, request, agent_id):
        from .models import AgentDailyPerformance
        
        from django.utils import timezone as tz
        from datetime import timedelta
        from django.db.models import Sum as DSum
        from django.core.paginator import Paginator

        agent = get_object_or_404(AgentProfile, id=agent_id)
        period = request.GET.get('period', 'week')  # week | month | all
        today = tz.localdate()

        all_perf = AgentDailyPerformance.objects.filter(agent=agent).order_by('-date')

        if period == 'week':
            # Group into ISO weeks; paginate by week
            weeks = {}
            for p in all_perf:
                iso = p.date.isocalendar()
                key = (iso.year, iso.week)
                weeks.setdefault(key, []).append(p)

            week_list = []
            for (year, week), rows in sorted(weeks.items(), reverse=True):
                rows_sorted = sorted(rows, key=lambda r: r.date)
                gross = sum(r.gross_interest for r in rows_sorted)
                net = sum(r.net for r in rows_sorted)
                withdrawn = sum(r.total_withdrawn for r in rows_sorted)
                week_list.append({
                    'label': f"Week {week}, {year}",
                    'rows': rows_sorted,
                    'gross': gross,
                    'net': net,
                    'withdrawn': withdrawn,
                })

            paginator = Paginator(week_list, 1)  # one week per page
            page_obj = paginator.get_page(request.GET.get('page', 1))
            groups = page_obj.object_list

        elif period == 'month':
            months = {}
            for p in all_perf:
                key = (p.date.year, p.date.month)
                months.setdefault(key, []).append(p)

            month_list = []
            for (year, month), rows in sorted(months.items(), reverse=True):
                rows_sorted = sorted(rows, key=lambda r: r.date)
                gross = sum(r.gross_interest for r in rows_sorted)
                net = sum(r.net for r in rows_sorted)
                withdrawn = sum(r.total_withdrawn for r in rows_sorted)
                import calendar
                month_list.append({
                    'label': f"{calendar.month_name[month]} {year}",
                    'rows': rows_sorted,
                    'gross': gross,
                    'net': net,
                    'withdrawn': withdrawn,
                })

            paginator = Paginator(month_list, 1)
            page_obj = paginator.get_page(request.GET.get('page', 1))
            groups = page_obj.object_list

        else:  # all — flat paginated list
            paginator = Paginator(all_perf, self.PAGE_SIZE)
            page_obj = paginator.get_page(request.GET.get('page', 1))
            totals = all_perf.aggregate(
                total_gross=DSum('gross_interest'),
                total_net=DSum('net'),
                total_withdrawn=DSum('total_withdrawn'),
            )
            return render(request, self.template_name, {
                'agent': agent,
                'period': period,
                'page_obj': page_obj,
                'rows': page_obj.object_list,
                'groups': None,
                'totals': totals,
            })

        overall = all_perf.aggregate(
            total_gross=DSum('gross_interest'),
            total_net=DSum('net'),
            total_withdrawn=DSum('total_withdrawn'),
        )
        return render(request, self.template_name, {
            'agent': agent,
            'period': period,
            'page_obj': page_obj,
            'groups': groups,
            'rows': None,
            'totals': overall,
        })


@method_decorator([login_required, user_passes_test(admin_required)], name='dispatch')
class AdminGiveAgentMoneyView(View):
    def post(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        try:
            amount = Decimal(request.POST.get("amount"))
            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect("loans:agent_detail", agent_id=agent.id)
        except:
            messages.error(request, "Invalid amount entered.")
            return redirect("loans:agent_detail", agent_id=agent.id)
        
        finance = CompanyFinance.get_balance()

        finance.total_amount -= amount
        finance.save()

        FinanceTransaction.objects.create(
            admin=request.user,
            transaction_type="withdraw",
            amount=amount,
            note=f"Given to agent {agent.user.username}"
        )

        # Add money to agent's amount_in_hand
        agent.amount_in_hand += amount
        agent.save()

        messages.success(request, f"{amount} SZL successfully given to {agent.user.get_full_name()}.")
        return redirect("loans:agent_detail", agent_id=agent.id)
    




class AdminFinanceDashboardView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser

    def get(self, request):
        cache_key = "admin_finance_dashboard"
        context = cache.get(cache_key)

        if not context:
            finance = CompanyFinance.get_balance()
            transactions = FinanceTransaction.objects.order_by('-timestamp')[:20]
            context = {
                "finance": finance,
                "transactions": transactions
            }
            cache.set(cache_key, context)

        return render(request, "loans/admin_finance_dashboard.html", context)


class DepositView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser

    def post(self, request):
        amount = Decimal(request.POST.get("amount", 0))
        if amount <= 0:
            messages.error(request, "Invalid deposit amount.")
            return redirect("loans:admin_finance_dashboard")

        finance = CompanyFinance.get_balance()
        finance.total_amount += amount
        finance.save()

        FinanceTransaction.objects.create(
            admin=request.user,
            transaction_type="deposit",
            amount=amount,
            note=request.POST.get("note", "")
        )

        messages.success(request, f"Deposited {amount} SZL successfully. Balance {finance.total_amount} SZL")
        return redirect("loans:admin_finance_dashboard")


class WithdrawView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser

    def post(self, request):
        amount = Decimal(request.POST.get("amount", 0))
        finance = CompanyFinance.get_balance()

        if amount <= 0:
            messages.error(request, "Invalid withdrawal amount.")
            return redirect("loans:admin_finance_dashboard")
        if amount > finance.total_amount:
            messages.error(request, "Insufficient company balance.")
            return redirect("loans:admin_finance_dashboard")

        finance.total_amount -= amount
        finance.save()

        FinanceTransaction.objects.create(
            admin=request.user,
            transaction_type="withdraw",
            amount=amount,
            note=request.POST.get("note", "")
        )

        # Create notification for all admins
        AdminNotification.create_withdrawal_notice(request.user, amount)

        messages.warning(request, f"Withdrew {amount} SZL successfully. Balance {finance.total_amount} SZL")
        return redirect("loans:admin_finance_dashboard")

class DismissNotificationView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser

    def get(self, request, pk):
        note = get_object_or_404(AdminNotification, pk=pk)
        note.dismissed_by.add(request.user)
        return redirect("loans:admin_dashboard")


class AgentTransactionRequestView(LoginRequiredMixin, View):
    """Handles both withdraw and send-to-admin requests."""

    def post(self, request, agent_id):
        agent = get_object_or_404(AgentProfile, id=agent_id)
        try:
            amount = Decimal(request.POST.get("amount"))
            note = request.POST.get("note", "")
            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect("loans:agent_dashboard")
            if amount > agent.amount_in_hand:
                messages.error(request, "Insufficient balance.")
                return redirect("loans:agent_dashboard")
        except:
            messages.error(request, "Invalid amount.")
            return redirect("loans:agent_dashboard")

        AdminTransactionRequest.objects.create(
            agent=agent,
            requested_amount=amount,
            transaction_type="withdraw",
            rejection_note=note  # optional note for admin
        )
        messages.success(request, f"withdrawal request submitted.")
        return redirect("loans:agent_dashboard")
    

from decimal import Decimal, InvalidOperation

class LoanCalculatorView(LoginRequiredMixin, View):
    template_name = "loans/loan_calculator.html"

    def get(self, request):
        settings = LoanSettings.objects.first()
        default_interest = settings.interest_percent if settings else Decimal("20.00")
        default_duration = settings.duration_days if settings else 20

        return render(request, self.template_name, {
            "default_interest": default_interest,
            "default_duration": default_duration,
            "calculated": False
        })

    def post(self, request):
        try:
            amount_raw = request.POST.get("amount")
            daily_raw = request.POST.get("daily_payment")

            if amount_raw and daily_raw:
                return render(request, self.template_name, {
                    "error": "Please fill either Loan Amount OR Daily Payment, not both.",
                    "calculated": False
                })

            interest_percent = Decimal(request.POST.get("interest_percent"))
            duration_days = int(request.POST.get("duration_days"))

            amount = Decimal(amount_raw) if amount_raw else None
            daily_payment = Decimal(daily_raw) if daily_raw else None

        except (InvalidOperation, ValueError):
            return render(request, self.template_name, {
                "error": "Invalid input values.",
                "calculated": False
            })

        if amount and daily_payment:
            return render(request, self.template_name, {
                "error": "Please fill either Loan Amount OR Daily Payment, not both.",
                "calculated": False
            })

        if not amount and not daily_payment:
            return render(request, self.template_name, {
                "error": "Please enter either Loan Amount or Daily Payment.",
                "calculated": False
            })

        interest_rate = interest_percent / Decimal("100")

        # ---- Forward Calculation ----
        if amount:
            interest_amount = amount * interest_rate
            total_payable = amount + interest_amount
            daily_payment = total_payable / duration_days

        # ---- Reverse Calculation ----
        else:
            total_payable = daily_payment * duration_days
            amount = total_payable / (1 + interest_rate)
            interest_amount = total_payable - amount

        return render(request, self.template_name, {
            "amount": round(amount, 2),
            "interest_percent": interest_percent,
            "duration_days": duration_days,
            "total_payable": round(total_payable, 2),
            "daily_payment": round(daily_payment, 2),
            "calculated": True
        })


@method_decorator([login_required, user_passes_test(admin_required)], name='dispatch')
class AgentLoanListView(View):
    def get(self, request, agent_id, status):
        agent = get_object_or_404(AgentProfile, id=agent_id)

        if status == "default":
            loans = Loan.objects.filter(
                customer__agent=agent,
                status="active"
            ).select_related("customer")
            loans = [loan for loan in loans if loan.days_missed >= 3]
        else:                                   
            loans = Loan.objects.filter(
                customer__agent=agent,
                status=status
            ).select_related("customer")

        return render(request, "loans/agent_loans_list.html", {
            "agent": agent,
            "loans": loans,
            "status": status
        })


from django.db import transaction

class DeleteLoanView(View):
    def post(self, request, loan_id):
        if not request.user.is_staff:
            messages.error(request, "Unauthorized action.")
            return redirect("loans:admin_agents")

        loan = get_object_or_404(Loan, id=loan_id)
        agent = loan.customer.agent  # adjust if relation differs

        with transaction.atomic():
            # ✅ SAME CALENDAR DAY ONLY
            if loan.days_missed <= 0:
                agent.amount_in_hand += loan.principal_amount
                agent.save(update_fields=["amount_in_hand"])

            loan.delete()

        messages.success(request, "Loan deleted successfully.")
        return redirect(request.META.get("HTTP_REFERER", "loans:admin_agents"))


class BatchCollectView(LoginRequiredMixin, View):
    template_name = 'loans/batch_collect.html'

    def get(self, request):
        from .models import get_holidays
        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = timezone.localdate()

        active_loans = (
            Loan.objects.filter(customer__agent=agent_profile, status='active')
            .select_related('customer')
            .annotate(
                paid_today=Exists(
                    Repayment.objects.filter(loan=OuterRef('pk'), date=today)
                )
            )
            .order_by(Lower('customer__name'))
        )

        holidays = get_holidays()
        due_loans = []
        for loan in active_loans:
            if not loan.paid_today:
                loan.days_remaining_cached = loan._compute_days_remaining(holidays)
                due_loans.append(loan)

        return render(request, self.template_name, {
            'due_loans': due_loans,
            'agent': agent_profile,
            'today': today,
        })


class BatchPaymentView(LoginRequiredMixin, View):
    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
            payments = data.get('payments', [])
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid request body'}, status=400)

        if not isinstance(payments, list) or not payments:
            return JsonResponse({'error': 'No payments provided'}, status=400)

        agent_profile = get_object_or_404(AgentProfile, user=request.user)
        today = date.today()
        now_time = timezone.now()

        results = []
        agent_total_added = Decimal('0')

        for item in payments:
            loan_id = item.get('loan_id')
            amount_str = item.get('amount')

            try:
                loan = Loan.objects.select_for_update().get(
                    id=loan_id, customer__agent=agent_profile
                )
            except Loan.DoesNotExist:
                results.append({'loan_id': loan_id, 'status': 'error', 'message': 'Loan not found'})
                continue

            try:
                amount = Decimal(str(amount_str)) if amount_str else loan.daily_payment
                if amount <= 0:
                    raise ValueError()
            except Exception:
                results.append({'loan_id': loan_id, 'status': 'error', 'message': 'Invalid amount'})
                continue

            if loan.last_payment_at and (now_time - loan.last_payment_at < timedelta(minutes=10)):
                results.append({
                    'loan_id': loan_id, 'status': 'skipped',
                    'message': 'Payment cooldown active', 'customer': loan.customer.name,
                })
                continue

            is_first_today = not Repayment.objects.filter(loan=loan, date=today).exists()

            Repayment.objects.create(
                loan=loan, date=today, amount_paid=amount, recorded_by=agent_profile
            )

            loan.total_paid += amount
            loan.last_payment_at = now_time
            loan.last_paid_date = today
            if is_first_today:
                loan.days_paid += 1
            agent_total_added += amount

            if loan.remaining_balance <= 0:
                loan.status = 'completed'
                _, upper, blacklist_recommended = evaluate_customer_loan_range(loan)
                customer = loan.customer
                customer.credit_score = upper
                if blacklist_recommended and not customer.blacklisted:
                    customer.blacklisted = True
                customer.save()

            loan.save()

            results.append({
                'loan_id': loan_id,
                'status': 'ok',
                'amount': str(amount),
                'customer': loan.customer.name,
                'remaining_balance': str(loan.remaining_balance),
            })

        agent_profile.amount_in_hand += agent_total_added
        agent_profile.save()

        total_amount = sum(Decimal(r['amount']) for r in results if r['status'] == 'ok')
        return JsonResponse({'results': results, 'total_amount': str(total_amount)})