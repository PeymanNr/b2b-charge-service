from django.db import models


class CreditRequestStatus(models.IntegerChoices):
    PENDING = 1, "در انتظار"
    APPROVED = 2, "تایید شده"
    REJECTED = 3, "رد شده"


class TransactionType(models.IntegerChoices):
    CREDIT = 1, "افزایش اعتبار"
    SALE = 2, "فروش شارژ"


class TransactionStatus(models.IntegerChoices):
    PENDING = 1, "در انتظار"
    APPROVED = 2, "تایید شده"
    REJECTED = 3, "رد شده"
