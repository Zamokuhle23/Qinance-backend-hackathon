from django.urls import path
from .views import AgentDashboardView, MarkPaymentView, LoanQualificationView, LoanOfferView, BatchCollectView, BatchPaymentView
from django.urls import path
from . import views

app_name = "loans"  # 

urlpatterns = [
    path('dashboard/', AgentDashboardView.as_view(), name='agent_dashboard'),
    path('mark-payment/<int:loan_id>/', MarkPaymentView.as_view(), name='mark_payment'),
    path("customers/", views.CustomerListView.as_view(), name="list_customers"),
    path("customers/new-loan/", views.CreateCustomerAndLoanView.as_view(), name="create_customer_loan"),
    path("customers/add-loan/", views.AddLoanExistingCustomerView.as_view(), name="add_loan_existing_customer"),
    path("customer/<int:customer_id>/qualification/", LoanQualificationView.as_view(), name="loan_qualification"),
    path("customer/<int:customer_id>/offer/", LoanOfferView.as_view(), name="loan_offer"),
    # loans/urls.py
    path('customer/<int:customer_id>/history/', views.CustomerHistoryView.as_view(), name='customer_history'),
    path('customer/<int:customer_id>/<int:loan_id>/history/', views.CustomerHistoryView.as_view(), name='customer_history_with_loan'),
    path("admin/dashboard/", views.AdminDashboardView.as_view(), name="admin_dashboard"),
    path("admin/customer/<int:customer_id>/adjust_credit/", views.AdjustCustomerCreditView.as_view(), name="adjust_customer_credit"),
    path("admin/update_loan_settings/", views.UpdateLoanSettingsView.as_view(), name="update_loan_settings"),
    path("admin/customers/", views.AdminCustomerListView.as_view(), name="admin_customers"),
    path("admin/customers/<int:pk>/edit/", views.AdminCustomerEditView.as_view(), name="admin_edit_customer"),
    path('admin/agents/', views.AdminAgentsView.as_view(), name='admin_agents'),
    path('admin/agents/invite/', views.GenerateAgentInviteView.as_view(), name='generate_agent_invite'),
    path('admin/agents/edit/<int:agent_id>/', views.EditAgentView.as_view(), name='edit_agent'),
    path("send-to-admin/", views.SendToAdminRequestView.as_view(), name="send_to_admin"),
    path("admin/agents/<int:agent_id>/", views.AgentDetailView.as_view(), name="agent_detail"),
    path("admin/agents/<int:agent_id>/transactions/", views.AgentTransactionLogView.as_view(), name="agent_transaction_log"),
    path("admin/agents/<int:agent_id>/performance/", views.AgentPerformanceHistoryView.as_view(), name="agent_performance_history"),
    path("admin/agents/<int:agent_id>/give-money/", views.AdminGiveAgentMoneyView.as_view(), name="give_agent_money"),
    path("admin/transaction/approve/<int:request_id>/", views.AdminApproveTransactionView.as_view(),name="approve_transaction",
    ),
    path("admin/finance/", views.AdminFinanceDashboardView.as_view(), name="admin_finance_dashboard"),
    path("admin/finance/deposit/", views.DepositView.as_view(), name="deposit_funds"),
    path("admin/finance/withdraw/", views.WithdrawView.as_view(), name="withdraw_funds"),
    path("admin/notification/<int:pk>/dismiss/", views.DismissNotificationView.as_view(), name="dismiss_notification"),
    path("agent/<int:agent_id>/withdraw/", views.AgentTransactionRequestView.as_view(), name="admin_give_agent_money"),
    path("loan-calculator/", views.LoanCalculatorView.as_view(), name="loan_calculator"),
    # loans/urls.py
    path("agents/<int:agent_id>/loans/<str:status>/", views.AgentLoanListView.as_view(), name="agent_loans"
    ),
    path("batch-collect/", BatchCollectView.as_view(), name="batch_collect"),
    path("batch-payment/", BatchPaymentView.as_view(), name="batch_payment"),
    path("loans/delete/<int:loan_id>/", views.DeleteLoanView.as_view(), name="delete_loan"),
    path(
    "reverse-payment/<int:loan_id>/",
    views.ReversePaymentView.as_view(),
    name="reverse_payment",
),


]