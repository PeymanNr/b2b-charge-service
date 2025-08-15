from django.contrib import admin
from charges.models import Charge


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Charge Model"""

    list_display = [
        'id', 'vendor__name', 'amount', 'phone_number',
        'created_at'
    ]
    search_fields = ['vendor__name', 'phone_number', 'amount']
    ordering = ['-created_at']
