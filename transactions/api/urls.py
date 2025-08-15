from django.urls import path
from .views import (
    TransactionViewSet,
    reconcile_vendor_balance,
    reconcile_all_balances,
    balance_report
)

transactions_list = TransactionViewSet.as_view({
    'get': 'list',
})

urlpatterns = [
    path('', transactions_list, name='transactions_list'),

    # Balance Reconciliation APIs
    path('reconcile/<int:vendor_id>/', reconcile_vendor_balance, name='reconcile_vendor_balance'),
    path('reconcile-all/', reconcile_all_balances, name='reconcile_all_balances'),
    path('balance-report/', balance_report, name='balance_report'),
]