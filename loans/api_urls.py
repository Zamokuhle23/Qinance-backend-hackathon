from django.urls import path
from . import api_views, ai_views

urlpatterns = [
    # Agent
    path('agent/dashboard/', api_views.AgentDashboardAPIView.as_view()),
    path('loans/<int:loan_id>/mark-payment/', api_views.MarkPaymentAPIView.as_view()),
    path('loans/<int:loan_id>/reverse-payment/', api_views.ReversePaymentAPIView.as_view()),
    path('customers/', api_views.CustomerListAPIView.as_view()),
    path('customers/new/', api_views.CreateCustomerLoanAPIView.as_view()),
    path('customers/add-loan/', api_views.AddLoanExistingAPIView.as_view()),
    path('customers/<int:customer_id>/qualification/', api_views.LoanQualificationAPIView.as_view()),
    path('customers/<int:customer_id>/offer/', api_views.LoanOfferAPIView.as_view()),
    path('customers/<int:customer_id>/history/', api_views.CustomerHistoryAPIView.as_view()),
    path('customers/<int:customer_id>/history/<int:loan_id>/', api_views.CustomerHistoryAPIView.as_view()),
    path('loans/reorder/', api_views.ReorderLoansAPIView.as_view()),
    path('batch-collect/', api_views.BatchCollectAPIView.as_view()),
    path('batch-payment/', api_views.BatchPaymentAPIView.as_view()),
    path('loan-calculator/', api_views.LoanCalculatorAPIView.as_view()),
    path('send-to-admin/', api_views.AgentSendToAdminAPIView.as_view()),
    path('pending-applications/', api_views.PendingLoanApplicationListCreateAPIView.as_view()),
    path('pending-applications/<int:pk>/action/', api_views.PendingLoanApplicationActionAPIView.as_view()),

    # Admin
    path('admin/dashboard/', api_views.AdminDashboardAPIView.as_view()),
    path('admin/customers/', api_views.AdminCustomerListAPIView.as_view()),
    path('admin/customers/<int:customer_id>/', api_views.AdminCustomerDetailAPIView.as_view()),
    path('admin/customers/<int:customer_id>/adjust-credit/', api_views.AdjustCustomerCreditAPIView.as_view()),
    path('admin/loan-settings/', api_views.UpdateLoanSettingsAPIView.as_view()),
    path('admin/agents/', api_views.AdminAgentsAPIView.as_view()),
    path('admin/agents/invite/', api_views.GenerateAgentInviteAPIView.as_view()),
    path('admin/agents/<int:agent_id>/', api_views.AgentDetailAPIView.as_view()),
    path('admin/agents/<int:agent_id>/edit/', api_views.EditAgentAPIView.as_view()),
    path('admin/agents/<int:agent_id>/give-money/', api_views.AdminGiveAgentMoneyAPIView.as_view()),
    path('admin/agents/<int:agent_id>/transactions/', api_views.AgentTransactionLogAPIView.as_view()),
    path('admin/agents/<int:agent_id>/performance/', api_views.AgentPerformanceHistoryAPIView.as_view()),
    path('admin/agents/<int:agent_id>/loans/<str:loan_status>/', api_views.AgentLoanListAPIView.as_view()),
    path('admin/agents/<int:agent_id>/withdraw/', api_views.AgentWithdrawRequestAPIView.as_view()),
    path('admin/transaction/<int:request_id>/approve/', api_views.AdminApproveTransactionAPIView.as_view()),
    path('admin/finance/', api_views.AdminFinanceDashboardAPIView.as_view()),
    path('admin/finance/deposit/', api_views.DepositAPIView.as_view()),
    path('admin/finance/withdraw/', api_views.WithdrawAPIView.as_view()),
    path('admin/notification/<int:pk>/dismiss/', api_views.DismissNotificationAPIView.as_view()),
    path('admin/loans/<int:loan_id>/delete/', api_views.DeleteLoanAPIView.as_view()),

    # AI
    path('ai/loans/<int:customer_id>/advice/', ai_views.LoanAdviceAPIView.as_view()),
    path('ai/customers/<int:customer_id>/health/', ai_views.BusinessHealthAPIView.as_view()),
    path('ai/ask/', ai_views.AskQinanceAPIView.as_view()),
    path('ai/logs/', ai_views.AILogListAPIView.as_view()),
    path('ai/stats/', ai_views.AILogStatsAPIView.as_view()),
]
