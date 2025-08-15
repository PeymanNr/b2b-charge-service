from django.db import models
from credits.models import CreditRequest
from utils.base_models import UUIDBaseModel, \
    TimeStampedModel
from utils.enums import TransactionType, TransactionStatus
from vendors.models import Vendor
from phonenumber_field.modelfields import PhoneNumberField


class TransactionManager(models.Manager):
    """Professional Transaction Manager for financial operations"""

    def get_vendor_transactions(self, vendor_id, start_date=None, end_date=None):
        """Get all transactions for a vendor with optional date filtering"""
        query = self.filter(vendor_id=vendor_id)

        if start_date:
            query = query.filter(created_at__gte=start_date)
        if end_date:
            query = query.filter(created_at__lte=end_date)

        return query.order_by('-created_at')


class Transaction(UUIDBaseModel, TimeStampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.IntegerField(choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    phone_number = PhoneNumberField(blank=True, null=True)
    credit_request = models.ForeignKey(CreditRequest, on_delete=models.SET_NULL, null=True, blank=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.IntegerField(
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING
    )
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    is_successful = models.BooleanField(default=True)

    objects = TransactionManager()

    class Meta:
        indexes = [
            models.Index(fields=['vendor', 'created_at']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['created_at']),
        ]

        ordering = ['-created_at']

    def __str__(self):
        if self.transaction_type == TransactionType.CREDIT.value:
            return f"Credit: {self.amount} to {self.vendor.name}"
        elif self.transaction_type == TransactionType.SALE.value:
            return f"Sale: {self.amount} from {self.vendor.name} for {self.phone_number}"
        else:
            return f"Transaction: {self.amount} - {self.vendor.name}"

    @property
    def transaction_type_display(self):
        return dict(TransactionType.choices)[self.transaction_type]
