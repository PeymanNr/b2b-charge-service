from django.contrib import admin
from django.utils.html import format_html
from transactions.models import Transaction
from utils.enums import TransactionType, TransactionStatus


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('vendor_name', 'transaction_type_display', 'status_display_colored', 'amount',
                    'balance_before_display', 'balance_change', 'balance_after_display',
                    'phone_number_display', 'created_at', 'is_successful')
    list_filter = ('transaction_type', 'status', 'is_successful', 'created_at')
    search_fields = ('vendor__name', 'phone_number', 'idempotency_key', 'description')
    readonly_fields = ('balance_before', 'balance_after', 'id', 'created_at', 'updated_at')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('vendor')
        return queryset

    def vendor_name(self, obj):
        return obj.vendor.name
    vendor_name.admin_order_field = 'vendor__name'
    vendor_name.short_description = 'Vendor'

    def transaction_type_display(self, obj):
        if obj.transaction_type == TransactionType.CREDIT.value:
            return format_html('<span style="color: green; font-weight: bold;">Credit</span>')
        elif obj.transaction_type == TransactionType.SALE.value:
            return format_html('<span style="color: blue; font-weight: bold;">Sale</span>')
        else:
            return format_html('<span style="color: gray; font-weight: bold;">Unknown</span>')

    def status_display_colored(self, obj):
        if obj.status == TransactionStatus.PENDING.value:
            return format_html('<span style="color: orange; font-weight: bold;">Pending</span>')
        elif obj.status == TransactionStatus.APPROVED.value:
            return format_html('<span style="color: green; font-weight: bold;">Approved</span>')
        elif obj.status == TransactionStatus.REJECTED.value:
            return format_html('<span style="color: red; font-weight: bold;">Rejected</span>')
        else:
            return format_html('<span style="color: gray; font-weight: bold;">Unknown</span>')

    def phone_number_display(self, obj):
        if obj.phone_number:
            return format_html('<span style="font-weight: bold;">{}</span>', obj.phone_number)
        return '-'

    def balance_before_display(self, obj):
        """Display balance before transaction with currency formatting"""
        if obj.balance_before is not None:
            formatted_balance = f"{obj.balance_before:,.0f}"
            return format_html('<span style="font-weight: bold; color: #666;">{} تومان</span>',
                             formatted_balance)
        return '-'
    balance_before_display.short_description = 'Balance Before'
    balance_before_display.admin_order_field = 'balance_before'

    def balance_after_display(self, obj):
        """Display balance after transaction with currency formatting"""
        if obj.balance_after is not None:
            formatted_balance = f"{obj.balance_after:,.0f}"
            return format_html('<span style="font-weight: bold; color: #333;">{} تومان</span>',
                             formatted_balance)
        return '-'
    balance_after_display.short_description = 'Balance After'
    balance_after_display.admin_order_field = 'balance_after'

    def balance_change(self, obj):
        """Display balance change with color coding"""
        if obj.balance_before is not None and obj.balance_after is not None:
            change = obj.balance_after - obj.balance_before
            if change > 0:
                formatted_change = f"+{change:,.0f}"
                return format_html('<span style="color: green; font-weight: bold;">{} تومان</span>', formatted_change)
            elif change < 0:
                formatted_change = f"{change:,.0f}"
                return format_html('<span style="color: red; font-weight: bold;">{} تومان</span>', formatted_change)
            else:
                return format_html('<span style="color: #666;">0 تومان</span>')
        return '-'
    balance_change.short_description = 'Balance Change'
