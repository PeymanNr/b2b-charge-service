from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, CheckConstraint
from utils.base_models import BaseModel


class Vendor(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    name = models.CharField(max_length=255, verbose_name="Vendor Name", db_index=True)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Vendor"
        verbose_name_plural = "Vendors"
        ordering = ['name']
        constraints = [
            CheckConstraint(check=Q(balance__gte=0), name="vendor_balance_non_negative"),
        ]

    def __str__(self):
        return self.name
