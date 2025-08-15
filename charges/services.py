import logging
from decimal import Decimal
import time

from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.db.models import F, Sum

from transactions.services import TransactionService
from utils.enums import TransactionType, TransactionStatus
from utils.security_managers import (
    SecurityAuditLogger,
    idempotency_manager,
    lock_manager,
    double_spending_protector,
    rate_limiter
)


logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class ChargeManagement:

    @staticmethod
    @transaction.atomic
    def charge_phone(vendor, phone_number, amount, idempotency_key=None):
        """
        Ultra-secure phone charging with comprehensive double-spending protection
        Returns (success: bool, transaction_obj, message: str)
        """
        from transactions.models import Transaction
        from datetime import timedelta

        if amount <= Decimal('0'):
            audit_logger.log_transaction_attempt(
                vendor.id, 'charge_phone', amount, False, "Invalid amount"
            )
            return False, None, "مبلغ باید مثبت باشد"

        # 🛡️ LEVEL 1: Rate Limiting Check
        rate_allowed, current_count = rate_limiter.check_rate_limit(
            f"charge_vendor_{vendor.id}",
            limit=100,
            window=60
        )

        if not rate_allowed:
            audit_logger.log_security_event(
                'RATE_LIMIT_EXCEEDED',
                vendor.id,
                {'rate_count': current_count, 'limit': 100},
                'WARNING'
            )
            return False, None, f"محدودیت نرخ درخواست رعایت نشده. تعداد فعلی: {current_count}/100"

        # 🛡️ LEVEL 1.5: Double Spending Protection
        spending_allowed, spending_key = double_spending_protector.create_spending_record(
            vendor_id=vendor.id,
            amount=amount,
            operation_type='mobile_charge',
            phone_number=str(phone_number)
        )

        if not spending_allowed:
            audit_logger.log_security_event(
                'DOUBLE_SPENDING_ATTEMPT',
                vendor.id,
                {'phone_number': str(phone_number), 'amount': str(amount)},
                'WARNING'
            )
            return False, None, "تراکنش مشابه در حال پردازش است. لطفاً منتظر بمانید."

        if not idempotency_key:
            idempotency_key = idempotency_manager.generate_key(
                vendor_id=vendor.id,
                operation_type='charge',
                phone_number=str(phone_number),
                amount=str(amount)
            )

        # 🛡️ LEVEL 2: Idempotency Check
        operation_data = {
            'vendor_id': vendor.id,
            'phone_number': str(phone_number),
            'amount': str(amount),
            'operation': 'charge_phone',
            'timestamp': time.time()
        }

        is_duplicate, existing_result = idempotency_manager.check_and_store_operation(
            idempotency_key, operation_data
        )

        if is_duplicate:
            if existing_result and existing_result.get('success'):
                try:
                    existing_tx = Transaction.objects.get(id=existing_result['transaction_id'])
                    audit_logger.log_security_event(
                        'DUPLICATE_CHARGE_PREVENTED',
                        vendor.id,
                        {'phone_number': str(phone_number), 'amount': str(amount)},
                        'WARNING'
                    )
                    return True, existing_tx, "شماره قبلاً شارژ شده (محافظت از تکرار)"
                except Transaction.DoesNotExist:
                    pass
            return False, None, "تلاش تکراری برای شارژ شناسایی شد"

        # 🛡️ LEVEL 3: Distributed Lock
        lock_key = f"vendor_charge_{vendor.id}"
        lock_acquired, lock_identifier = lock_manager.acquire_lock(lock_key, timeout=30)

        if not lock_acquired:
            audit_logger.log_security_event(
                'CHARGE_LOCK_FAILED',
                vendor.id,
                {'phone_number': str(phone_number), 'amount': str(amount)},
                'WARNING'
            )
            return False, None, "سیستم مشغول است، لطفاً مجدداً تلاش کنید"

        try:
            # 🛡️ LEVEL 4: Database Transaction with Full Isolation
            with transaction.atomic():
                # Get vendor with pessimistic lock
                from vendors.models import Vendor
                fresh_vendor = Vendor.objects.select_for_update(nowait=False).get(id=vendor.id)

                # Optimistic locking check
                if fresh_vendor.version != vendor.version:
                    audit_logger.log_security_event(
                        'CHARGE_VERSION_CONFLICT',
                        vendor.id,
                        {'expected_version': vendor.version, 'actual_version': fresh_vendor.version},
                        'ERROR'
                    )
                    raise ValidationError("داده‌های فروشنده در حین پردازش تغییر کرد")

                # 🛡️ LEVEL 5: Business Logic Validation
                if not fresh_vendor.is_active:
                    audit_logger.log_security_event(
                        'CHARGE_INACTIVE_VENDOR',
                        vendor.id,
                        {'phone_number': str(phone_number), 'amount': str(amount)},
                        'WARNING'
                    )
                    raise ValidationError("حساب فروشنده فعال نیست")

                if fresh_vendor.balance < amount:
                    audit_logger.log_security_event(
                        'CHARGE_INSUFFICIENT_BALANCE',
                        vendor.id,
                        {'available': str(fresh_vendor.balance), 'required': str(amount)},
                        'WARNING'
                    )
                    raise ValidationError(f"موجودی ناکافی. موجود: {fresh_vendor.balance}, مورد نیاز: {amount}")

                # Check daily limit - Use vendor's actual daily_limit
                from django.utils import timezone
                today_charges = Transaction.objects.filter(
                    vendor=fresh_vendor,
                    transaction_type=TransactionType.SALE.value,
                    created_at__date=timezone.now().date(),
                    is_successful=True
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

                # Use vendor's actual daily_limit instead of hardcoded value
                if today_charges + amount > fresh_vendor.daily_limit:
                    audit_logger.log_security_event(
                        'CHARGE_DAILY_LIMIT_EXCEEDED',
                        vendor.id,
                        {
                            'today_charges': str(today_charges),
                            'vendor_daily_limit': str(fresh_vendor.daily_limit),
                            'requested': str(amount),
                            'would_exceed_by': str((today_charges + amount) - fresh_vendor.daily_limit)
                        },
                        'WARNING'
                    )
                    raise ValidationError(f"محدودیت روزانه رعایت نشده. محدودیت: {fresh_vendor.daily_limit:,} تومان، مصرف امروز: {today_charges:,} تومان")

                # 🛡️ LEVEL 6: Smart Double Spending Protection
                # Instead of time-based protection, use idempotency and fingerprinting
                # This allows legitimate multiple purchases while preventing true double spending

                # Option 1: Strong idempotency enforcement (recommended for production)
                # If no idempotency_key provided by client, this indicates potential double spending
                if not idempotency_key or len(idempotency_key) < 10:
                    # Generate a warning but allow the transaction with auto-generated key
                    audit_logger.log_security_event(
                        'WEAK_IDEMPOTENCY_KEY',
                        vendor.id,
                        {
                            'phone_number': str(phone_number),
                            'amount': str(amount),
                            'provided_key': idempotency_key or 'None'
                        },
                        'WARNING'
                    )

                # Option 2: Check for suspicious rapid identical transactions (rate limiting approach)
                # Only flag if there are too many identical transactions in a very short burst
                recent_identical_count = Transaction.objects.filter(
                    vendor=fresh_vendor,
                    phone_number=phone_number,
                    amount=amount,
                    transaction_type=TransactionType.SALE.value,
                    created_at__gte=timezone.now() - timedelta(seconds=10),  # Very short window
                    is_successful=True
                ).count()

                if recent_identical_count >= 3:  # Allow 2, block from 3rd
                    audit_logger.log_security_event(
                        'SUSPICIOUS_RAPID_IDENTICAL_TRANSACTIONS',
                        vendor.id,
                        {
                            'phone_number': str(phone_number),
                            'amount': str(amount),
                            'count_in_10sec': recent_identical_count
                        },
                        'WARNING'
                    )
                    raise ValidationError("تعداد زیادی تراکنش یکسان در زمان کوتاه شناسایی شد. لطفاً از idempotency_key استفاده کنید.")

                # 🛡️ LEVEL 7: Atomic Balance Update
                old_balance = fresh_vendor.balance
                new_balance = old_balance - amount

                if new_balance < Decimal('0'):
                    audit_logger.log_security_event(
                        'CHARGE_NEGATIVE_BALANCE',
                        vendor.id,
                        {'old_balance': str(old_balance), 'amount': str(amount)},
                        'ERROR'
                    )
                    raise ValidationError("تراکنش باعث منفی شدن موجودی می‌شود")

                updated_rows = Vendor.objects.filter(
                    id=fresh_vendor.id,
                    version=fresh_vendor.version,  # Optimistic lock
                    balance__gte=amount       # Ensure sufficient balance
                ).update(
                    balance=F('balance') - amount,
                    version=F('version') + 1
                )

                if updated_rows == 0:
                    audit_logger.log_security_event(
                        'CHARGE_BALANCE_UPDATE_FAILED',
                        vendor.id,
                        {'amount': str(amount)},
                        'ERROR'
                    )
                    raise ValidationError("به‌روزرسانی موجودی ناموفق - تغییر همزمان شناسایی شد")

                fresh_vendor.refresh_from_db()

                # Create transaction record using centralized service
                transaction_obj = TransactionService.create_transaction_record(
                    vendor=fresh_vendor,
                    transaction_type=TransactionType.SALE.value,
                    amount=amount,
                    balance_before=old_balance,
                    balance_after=fresh_vendor.balance,
                    idempotency_key=idempotency_key,
                    phone_number=phone_number,
                    description=f"Phone charge: {phone_number} - {amount}"
                )

                # 🆕 LEVEL 8: Create Charge Record
                from charges.models import Charge

                # Create charge record
                Charge.objects.create(
                    vendor=fresh_vendor,
                    phone_number=phone_number,
                    amount=amount
                )

                # نهایی کردن رکورد Double Spending Protection
                double_spending_protector.finalize_spending_record(
                    spending_key,
                    str(transaction_obj.id),
                    success=True
                )

                result_data = {
                    'success': True,
                    'transaction_id': str(transaction_obj.id),
                    'vendor_id': vendor.id,
                    'phone_number': str(phone_number),
                    'amount': str(amount),
                    'old_balance': str(old_balance),
                    'new_balance': str(fresh_vendor.balance),
                    'completed_at': time.time()
                }
                idempotency_manager.update_operation_result(idempotency_key, result_data)

                # Update the original vendor object's balance and version
                vendor.balance = fresh_vendor.balance
                vendor.version = fresh_vendor.version

                audit_logger.log_transaction_attempt(
                    vendor.id, 'charge_phone', amount, True, None
                )

                logger.info(f"Phone charged successfully - Vendor: {vendor.id}, Phone: {phone_number}, Amount: {amount}")
                return True, transaction_obj, "شماره با موفقیت شارژ شد"

        except Exception as e:
            logger.error(f"Error charging phone for vendor {vendor.id}: {str(e)}")
            audit_logger.log_transaction_attempt(
                vendor.id, 'charge_phone', amount, False, str(e)
            )

            # نهایی کردن رکورد Double Spending Protection با شکست
            double_spending_protector.finalize_spending_record(
                spending_key,
                transaction_id="",
                success=False
            )

            error_data = {
                'success': False,
                'error': str(e),
                'failed_at': time.time()
            }
            idempotency_manager.update_operation_result(idempotency_key, error_data)
            return False, None, f"خطا: {str(e)}"

        finally:
            # Always release distributed lock
            lock_manager.release_lock(lock_key, lock_identifier)
