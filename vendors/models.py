from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, CheckConstraint
from decimal import Decimal
from utils.base_models import TimeStampedModel
import logging
from django.core.exceptions import ValidationError


logger = logging.getLogger(__name__)


class VendorManager(models.Manager):
    """Custom manager for Vendor with professional financial operations"""

    def get_with_lock(self, vendor_id):
        """Get vendor with SELECT FOR UPDATE to prevent race conditions"""
        return self.select_for_update().get(id=vendor_id)

    def reconcile_all_balances(self):
        """Reconcile all vendor balances"""
        from transactions.services import BalanceReconciliationService
        return BalanceReconciliationService.reconcile_all_balances()


class Vendor(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    name = models.CharField(max_length=255, verbose_name="Vendor Name", db_index=True)
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    daily_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('1000000.00')
    )

    objects = VendorManager()

    class Meta:
        verbose_name = "Vendor"
        verbose_name_plural = "Vendors"
        ordering = ['name']
        constraints = [
            CheckConstraint(check=Q(balance__gte=0), name="vendor_balance_non_negative"),
            CheckConstraint(check=Q(daily_limit__gte=0), name="vendor_daily_limit_non_negative"),
        ]
        indexes = [
            models.Index(fields=['is_active', 'created_at']),
            models.Index(fields=['balance']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Additional validation"""
        if self.balance < Decimal('0'):
            raise ValidationError("Balance cannot be negative")
        if self.daily_limit < Decimal('0'):
            raise ValidationError("Daily limit cannot be negative")