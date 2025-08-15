import uuid
from django.db import models


class TimeStampedModel(models.Model):
    """TimeStampedModel with regular Django ID for main entities like Vendor"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDBaseModel(models.Model):
    """Base model with UUID for sensitive entities like Transaction"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CreatedAtOnlyModel(models.Model):
    """Base model for entities that only need creation timestamp (like charges)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
