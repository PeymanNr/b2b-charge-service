from django.contrib import admin
from django.utils.html import format_html
from vendors.models import Vendor
from decimal import Decimal


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'balance_display', 'version', 'is_active', 'created_at', 'updated_at', 'transaction_count')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'user__username', 'user__email')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('user')
        return queryset

    def transaction_count(self, obj):
        return obj.transactions.count()
    transaction_count.short_description = 'Transaction Count'

    def balance_display(self, obj):
        if obj.balance < Decimal('10000'):
            return format_html('<span style="color: red;">{}</span>', obj.balance)
        return format_html('<span style="color: green;">{}</span>', obj.balance)
    balance_display.short_description = 'Balance'
