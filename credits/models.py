from django.db import models
from django.db.models import CheckConstraint, Q
from utils.base_models import UUIDBaseModel, TimeStampedModel
from utils.enums import CreditRequestStatus
from vendors.models import Vendor
import logging

logger = logging.getLogger(__name__)


class CreditRequestManager(models.Manager):
    """Professional manager for credits requests with security features"""

    def get_vendor_requests(self, vendor_id):
        """Get all credits requests for a vendor"""
        query = self.filter(vendor_id=vendor_id).order_by('-created_at')
        return query

    def approve_request(self, request_id, admin_user):
        """Approve a credits request using service layer"""
        from .services import CreditService
        return CreditService.approve_credit_request(request_id, admin_user)

    def reject_request(self, request_id, admin_user, reason=None):
        """Reject a credits request using service layer"""
        from .services import CreditService
        return CreditService.reject_credit_request(request_id, admin_user, reason)


class CreditRequest(UUIDBaseModel, TimeStampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='credit_requests')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.IntegerField(
        choices=CreditRequestStatus.choices,
        default=CreditRequestStatus.PENDING
    )
    rejection_reason = models.TextField(null=True, blank=True)

    objects = CreditRequestManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['vendor', 'status']),
        ]
        constraints = [
            CheckConstraint(check=Q(amount__gt=0), name="credit_amount_positive"),
        ]

    def __str__(self):
        return f"{self.vendor.name} - {self.amount} - {self.get_status_display()}"

    def get_status_display(self):
        return dict(CreditRequestStatus.choices)[self.status]


