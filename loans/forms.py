from django import forms
from .models import Loan,Customer

class LoanForm(forms.ModelForm):
    class Meta:
        model = Loan
        fields = ['principal_amount', 'interest_rate', 'duration_days']
        widgets = {
            'interest_rate': forms.NumberInput(attrs={'readonly': 'readonly'}),
            'duration_days': forms.NumberInput(attrs={'readonly': 'readonly'}),
        }


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'national_id', 'location']
