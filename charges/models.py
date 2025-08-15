from django.db import models
from django.db.models import CheckConstraint, Q
from phonenumber_field.modelfields import PhoneNumberField
from utils.base_models import CreatedAtOnlyModel
from vendors.models import Vendor
import logging

logger = logging.getLogger(__name__)


class ChargeManager(models.Manager):
    """Manager for Charge operations"""

    def get_vendor_charges(self, vendor_id, limit=None):
        """Get all charges made by a vendor"""
        queryset = self.filter(vendor_id=vendor_id).order_by('-created_at')
        if limit:
            queryset = queryset[:limit]
        return queryset


class Charge(CreatedAtOnlyModel):
    """Model to track individual phone charge transactions"""

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='charges',
        verbose_name="vendor charge"
    )
    phone_number = PhoneNumberField(verbose_name="phone number")
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="charge amount"
    )

    objects = ChargeManager()

    class Meta:
        verbose_name = "charge"
        verbose_name_plural = "charges"
        ordering = ['-created_at']
        constraints = [
            CheckConstraint(check=Q(amount__gt=0), name="charge_amount_positive"),
        ]
        indexes = [
            models.Index(fields=['vendor', '-created_at']),
            models.Index(fields=['phone_number', '-created_at']),
        ]

    def __str__(self):
        return f"{self.phone_number} - {self.amount} - {self.vendor.name}"
