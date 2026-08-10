from datetime import date
from .models import Customer, Repayment

def agent_performance(agent):
    total_customers = Customer.objects.filter(agent=agent).count()
    paid_today = Repayment.objects.filter(
        recorded_by=agent.user,
        date=date.today()
    ).values('loan__customer').distinct().count()

    if total_customers == 0:
        return 0
    return round((paid_today / total_customers) * 100, 2)


import holidays
from loans.models import PublicHoliday

def load_eswatini_holidays(year):
    sz_holidays = holidays.country_holidays("SZ", years=year)

    created = 0

    for date_obj, name in sz_holidays.items():
        _, was_created = PublicHoliday.objects.get_or_create(
            holiday_date=date_obj,
            defaults={"name": name}
        )
        if was_created:
            created += 1

    return created