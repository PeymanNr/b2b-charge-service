from django.db import transaction
from django.db.models import F, Sum
from django.core.exceptions import ValidationError
from typing import Tuple, Optional
from decimal import Decimal
import logging
import time

from .models import CreditRequest
from transactions.models import Transaction
from transactions.services import TransactionService
from utils.enums import CreditRequestStatus, TransactionStatus, TransactionType
from utils.security_managers import (
    lock_manager,
    idempotency_manager,
    SecurityAuditLogger,
    double_spending_protector,
    rate_limiter
)

logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class CreditService:
    """
    Ultra-secure Credit Service with comprehensive protection against:
    - Race conditions
    - Double spending
    - Concurrent modifications
    - Duplicate requests
    """

    @staticmethod
    def create_credit_request(vendor, amount: Decimal) -> Tuple[bool, str, Optional[CreditRequest]]:
        """
        Create a new credits request with full security measures and daily limit check
        """
        spending_key = None  # تعریف اولیه برای جلوگیری از خطا

        try:
            if amount <= Decimal('0'):
                return False, "مبلغ باید بیشتر از صفر باشد", None

            # 🛡️ LEVEL 1: Rate Limiting Check
            rate_allowed, current_count = rate_limiter.check_rate_limit(
                f"credit_request_vendor_{vendor.id}",
                limit=10,  # کمتر از charge - 10 درخواست در دقیقه
                window=60
            )

            if not rate_allowed:
                audit_logger.log_security_event(
                    'CREDIT_REQUEST_RATE_LIMIT_EXCEEDED',
                    vendor.id,
                    {'rate_count': current_count, 'limit': 10},
                    'WARNING'
                )
                return False, f"محدودیت نرخ درخواست کردیت رعایت نشده. تعداد فعلی: {current_count}/10", None

            # 🛡️ LEVEL 1.5: Double Spending Protection for Credit Requests
            spending_allowed, spending_key = double_spending_protector.create_spending_record(
                vendor_id=vendor.id,
                amount=amount,
                operation_type='credit_request',
                phone_number=None
            )

            if not spending_allowed:
                audit_logger.log_security_event(
                    'CREDIT_REQUEST_DOUBLE_SPENDING_ATTEMPT',
                    vendor.id,
                    {'amount': str(amount)},
                    'WARNING'
                )
                return False, "درخواست کردیت مشابه در حال پردازش است. لطفاً منتظر بمانید.", None

            # Check daily credits limit BEFORE creating the request to prevent money laundering
            from django.utils import timezone
            today_credits = Transaction.objects.filter(
                vendor=vendor,
                transaction_type=TransactionType.CREDIT.value,
                created_at__date=timezone.now().date(),
                is_successful=True
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Use vendor's daily_limit for credits operations validation
            if today_credits + amount > vendor.daily_limit:
                audit_logger.log_security_event(
                    'CREDIT_REQUEST_DAILY_LIMIT_EXCEEDED',
                    vendor.id,
                    {
                        'today_credits': str(today_credits),
                        'vendor_daily_limit': str(vendor.daily_limit),
                        'requested': str(amount),
                        'would_exceed_by': str((today_credits + amount) - vendor.daily_limit)
                    },
                    'WARNING'
                )

                # نهایی کردن رکورد Double Spending Protection با شکست
                double_spending_protector.finalize_spending_record(
                    spending_key,
                    transaction_id="",
                    success=False
                )

                return False, f"محدودیت روزانه افزایش اعتبار رعایت نشده. محدودیت: {vendor.daily_limit:,} تومان، افزایش امروز: {today_credits:,} تومان", None

            # Generate idempotency key for duplicate prevention
            idempotency_key = idempotency_manager.generate_key(
                vendor_id=vendor.id,
                operation_type='create_credit_request',
                amount=str(amount),
                timestamp=int(time.time())
            )

            # Check for duplicate requests
            is_duplicate, existing_result = idempotency_manager.check_and_store_operation(
                idempotency_key, {
                    'vendor_id': vendor.id,
                    'amount': str(amount),
                    'operation': 'create_credit_request',
                    'timestamp': time.time()
                }
            )

            if is_duplicate:
                audit_logger.log_security_event(
                    'DUPLICATE_CREDIT_REQUEST',
                    vendor.id,
                    {'amount': str(amount)},
                    'WARNING'
                )
                return False, "درخواست تکراری شناسایی شد", None

            with transaction.atomic():
                # Create credits request
                credit_request = CreditRequest.objects.create(
                    vendor=vendor,
                    amount=amount,
                    status=CreditRequestStatus.PENDING
                )

                # Create corresponding pending transaction
                TransactionService.create_pending_transaction(
                    vendor=vendor,
                    transaction_type=TransactionType.CREDIT.value,
                    amount=amount,
                    idempotency_key=idempotency_key,
                    credit_request=credit_request,
                    description=f"Credit request pending: {amount}"
                )

                # Update idempotency cache with success
                idempotency_manager.update_operation_result(idempotency_key, {
                    'success': True,
                    'credit_request_id': str(credit_request.id),
                    'amount': str(amount),
                    'completed_at': time.time()
                })

                # نهایی کردن رکورد Double Spending Protection با موفقیت
                double_spending_protector.finalize_spending_record(
                    spending_key,
                    str(credit_request.id),
                    success=True
                )

                audit_logger.log_security_event(
                    'CREDIT_REQUEST_CREATED',
                    vendor.id,
                    {'request_id': str(credit_request.id), 'amount': str(amount)},
                    'INFO'
                )

                logger.info(f"Credit request created: {credit_request.id} for vendor {vendor.id}")
                return True, "درخواست اعتبار با موفقیت ایجاد شد", credit_request

        except Exception as e:
            # نهایی کردن رکورد Double Spending Protection با شکست
            double_spending_protector.finalize_spending_record(
                spending_key,
                transaction_id="",
                success=False
            )

            audit_logger.log_security_event(
                'CREDIT_REQUEST_CREATION_FAILED',
                vendor.id if vendor else None,
                {'error': str(e), 'amount': str(amount)},
                'ERROR'
            )
            logger.error(f"Error creating credits request: {str(e)}")
            return False, f"خطا در ایجاد درخواست: {str(e)}", None

    @staticmethod
    def approve_credit_request(request_id, admin_user) -> Tuple[bool, str]:
        """
        Approve credits request with ultra-secure balance increase
        Protected against race conditions and double processing
        """
        # Distributed lock for this specific request
        lock_key = f"credit_approval_{request_id}"
        lock_acquired, lock_identifier = lock_manager.acquire_lock(lock_key, timeout=30)

        if not lock_acquired:
            audit_logger.log_security_event(
                'CREDIT_APPROVAL_LOCK_FAILED',
                None,
                {'request_id': str(request_id)},
                'WARNING'
            )
            return False, "سیستم مشغول است، لطفاً مجدداً تلاش کنید"

        try:
            with transaction.atomic():
                # Lock the credits request
                credit_request = CreditRequest.objects.select_for_update().get(id=request_id)

                # Business validation
                if credit_request.status != CreditRequestStatus.PENDING:
                    audit_logger.log_security_event(
                        'CREDIT_APPROVAL_ALREADY_PROCESSED',
                        credit_request.vendor.id,
                        {'request_id': str(request_id), 'current_status': credit_request.status},
                        'WARNING'
                    )
                    return False, f"درخواست قبلاً پردازش شده: {credit_request.get_status_display()}"

                # Get the pending transaction (should exist from create_credit_request)
                pending_transaction = Transaction.objects.filter(
                    credit_request=credit_request,
                    status=TransactionStatus.PENDING.value
                ).first()

                if not pending_transaction:
                    audit_logger.log_security_event(
                        'CREDIT_APPROVAL_NO_PENDING_TRANSACTION',
                        credit_request.vendor.id,
                        {'request_id': str(request_id)},
                        'ERROR'
                    )
                    return False, "تراکنش در انتظار یافت نشد"

                # Check if already approved (double check)
                if pending_transaction.is_successful:
                    return False, "درخواست قبلاً تایید شده است"

                # Get vendor with lock for balance update
                from vendors.models import Vendor
                fresh_vendor = Vendor.objects.select_for_update().get(id=credit_request.vendor.id)

                # Validate daily limit
                from django.utils import timezone
                today_credits = Transaction.objects.filter(
                    vendor=fresh_vendor,
                    transaction_type=TransactionType.CREDIT.value,
                    created_at__date=timezone.now().date(),
                    is_successful=True
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

                if today_credits + credit_request.amount > fresh_vendor.daily_limit:
                    audit_logger.log_security_event(
                        'CREDIT_APPROVAL_DAILY_LIMIT_EXCEEDED',
                        fresh_vendor.id,
                        {
                            'today_credits': str(today_credits),
                            'vendor_daily_limit': str(fresh_vendor.daily_limit),
                            'requested': str(credit_request.amount),
                            'would_exceed_by': str((today_credits + credit_request.amount) - fresh_vendor.daily_limit)
                        },
                        'WARNING'
                    )
                    return False, f"محدودیت روزانه افزایش اعتبار رعایت نشده. محدودیت: {fresh_vendor.daily_limit:,} تومان"

                # Store old balance for transaction record
                old_balance = fresh_vendor.balance

                # Atomic balance update with version increment
                updated_rows = Vendor.objects.filter(
                    id=fresh_vendor.id,
                    version=fresh_vendor.version
                ).update(
                    balance=F('balance') + credit_request.amount,
                    version=F('version') + 1
                )

                if updated_rows == 0:
                    audit_logger.log_security_event(
                        'CREDIT_APPROVAL_BALANCE_UPDATE_FAILED',
                        fresh_vendor.id,
                        {'amount': str(credit_request.amount)},
                        'ERROR'
                    )
                    return False, "به‌روزرسانی موجودی ناموفق - تغییر همزمان شناسایی شد"

                fresh_vendor.refresh_from_db()

                # Update the existing pending transaction instead of creating a new one
                TransactionService.update_transaction_status(
                    transaction_id=pending_transaction.id,
                    status=TransactionStatus.APPROVED.value,
                    balance_after=fresh_vendor.balance,
                    is_successful=True,
                    description=f"Credit request approved: {credit_request.amount}"
                )

                # Update the transaction record with proper balance info
                pending_transaction.balance_before = old_balance
                pending_transaction.balance_after = fresh_vendor.balance
                pending_transaction.save(update_fields=['balance_before', 'balance_after'])

                # Update request status
                credit_request.status = CreditRequestStatus.APPROVED
                credit_request.save(update_fields=['status', 'updated_at'])

                audit_logger.log_security_event(
                    'CREDIT_REQUEST_APPROVED',
                    credit_request.vendor.id,
                    {
                        'request_id': str(request_id),
                        'amount': str(credit_request.amount),
                        'admin_user': admin_user.username if admin_user else 'system',
                        'transaction_id': str(pending_transaction.id),
                        'old_balance': str(old_balance),
                        'new_balance': str(fresh_vendor.balance)
                    },
                    'INFO'
                )

                logger.info(f"Credit request {request_id} approved successfully by {admin_user}")
                return True, "درخواست اعتبار با موفقیت تایید شد"

        except CreditRequest.DoesNotExist:
            audit_logger.log_security_event(
                'CREDIT_APPROVAL_NOT_FOUND',
                None,
                {'request_id': str(request_id)},
                'ERROR'
            )
            return False, "درخواست اعتبار یافت نشد"
        except Exception as e:
            audit_logger.log_security_event(
                'CREDIT_APPROVAL_ERROR',
                None,
                {'request_id': str(request_id), 'error': str(e)},
                'ERROR'
            )
            logger.error(f"Error approving credits request {request_id}: {str(e)}")
            return False, f"خطا در تایید درخواست: {str(e)}"
        finally:
            # Always release the lock
            lock_manager.release_lock(lock_key, lock_identifier)

    @staticmethod
    def reject_credit_request(request_id, admin_user, reason: Optional[str] = None) -> Tuple[bool, str]:
        """
        Reject credits request with proper logging
        """
        # Lock for atomic rejection
        lock_key = f"credit_rejection_{request_id}"
        lock_acquired, lock_identifier = lock_manager.acquire_lock(lock_key, timeout=15)

        if not lock_acquired:
            return False, "سیستم مشغول است، لطفاً مجدداً تلاش کنید"

        try:
            with transaction.atomic():
                credit_request = CreditRequest.objects.select_for_update().get(id=request_id)

                # Business validation
                if credit_request.status != CreditRequestStatus.PENDING:
                    audit_logger.log_security_event(
                        'CREDIT_REJECTION_ALREADY_PROCESSED',
                        credit_request.vendor.id,
                        {'request_id': str(request_id), 'current_status': credit_request.status},
                        'WARNING'
                    )
                    return False, f"درخواست قبلاً پردازش شده: {credit_request.get_status_display()}"

                # Update request status
                credit_request.status = CreditRequestStatus.REJECTED
                credit_request.rejection_reason = reason
                credit_request.save(update_fields=['status', 'rejection_reason', 'updated_at'])

                # Update pending transaction using centralized service
                pending_transactions = Transaction.objects.filter(
                    credit_request=credit_request,
                    status=TransactionStatus.PENDING.value
                )

                for pending_tx in pending_transactions:
                    TransactionService.update_transaction_status(
                        transaction_id=pending_tx.id,
                        status=TransactionStatus.REJECTED.value,
                        is_successful=False,
                        description=f"Credit request rejected: {credit_request.amount} - Reason: {reason or 'No reason provided'}"
                    )

                audit_logger.log_security_event(
                    'CREDIT_REQUEST_REJECTED',
                    credit_request.vendor.id,
                    {
                        'request_id': str(request_id),
                        'amount': str(credit_request.amount),
                        'reason': reason,
                        'admin_user': admin_user.username if admin_user else 'system'
                    },
                    'INFO'
                )

                logger.info(f"Credit request {request_id} rejected by {admin_user}")
                return True, "درخواست اعتبار رد شد"

        except CreditRequest.DoesNotExist:
            return False, "درخواست اعتبار یافت نشد"
        except Exception as e:
            audit_logger.log_security_event(
                'CREDIT_REJECTION_ERROR',
                None,
                {'request_id': str(request_id), 'error': str(e)},
                'ERROR'
            )
            logger.error(f"Error rejecting credits request {request_id}: {str(e)}")
            return False, f"خطا در رد درخواست: {str(e)}"
        finally:
            lock_manager.release_lock(lock_key, lock_identifier)


class CreditManagement:
    """Ultra-secure balance management service using security managers"""

    @staticmethod
    @transaction.atomic
    def increase_balance(vendor, amount, credit_request=None, idempotency_key=None):
        """
        Ultra-secure balance increase with comprehensive protection
        Returns (success: bool, transaction_obj, message: str)
        """
        from transactions.models import Transaction

        if amount <= Decimal('0'):
            audit_logger.log_transaction_attempt(
                vendor.id, 'increase_balance', amount, False, "Invalid amount"
            )
            return False, None, "مبلغ باید مثبت باشد"

        # Generate idempotency key if not provided
        if not idempotency_key:
            idempotency_key = idempotency_manager.generate_key(
                vendor_id=vendor.id,
                operation_type='credits',
                amount=str(amount),
                credit_request_id=credit_request.id if credit_request else None
            )

        # 🔒 LEVEL 1: Idempotency Check
        operation_data = {
            'vendor_id': vendor.id,
            'amount': str(amount),
            'operation': 'increase_balance',
            'timestamp': time.time()
        }

        is_duplicate, existing_result = idempotency_manager.check_and_store_operation(
            idempotency_key, operation_data
        )

        if is_duplicate:
            if existing_result and 'transaction_id' in existing_result:
                # Return the existing transaction
                try:
                    existing_tx = Transaction.objects.get(id=existing_result['transaction_id'])
                    audit_logger.log_security_event(
                        'DUPLICATE_BALANCE_INCREASE_PREVENTED',
                        vendor.id,
                        {'idempotency_key': idempotency_key},
                        'WARNING'
                    )
                    return True, existing_tx, "تراکنش قبلاً پردازش شده (محافظت از تکرار)"
                except Transaction.DoesNotExist:
                    pass
            return False, None, "تراکنش تکراری شناسایی شد"

        # 🔒 LEVEL 2: Distributed Lock
        lock_key = f"vendor_balance_{vendor.id}"
        lock_acquired, lock_identifier = lock_manager.acquire_lock(lock_key, timeout=30)

        if not lock_acquired:
            audit_logger.log_security_event(
                'BALANCE_INCREASE_LOCK_FAILED',
                vendor.id,
                {'amount': str(amount)},
                'WARNING'
            )
            return False, None, "سیستم مشغول است، لطفاً مجدداً تلاش کنید"

        try:
            # 🔒 LEVEL 3: Database Lock with Version Check
            with transaction.atomic():
                # Get fresh vendor data with SELECT FOR UPDATE
                from vendors.models import Vendor
                fresh_vendor = Vendor.objects.select_for_update().get(id=vendor.id)

                # Optimistic locking - check version hasn't changed
                if fresh_vendor.version != vendor.version:
                    audit_logger.log_security_event(
                        'BALANCE_INCREASE_VERSION_CONFLICT',
                        vendor.id,
                        {'expected_version': vendor.version, 'actual_version': fresh_vendor.version},
                        'ERROR'
                    )
                    raise ValidationError("داده‌های فروشنده توسط فرآیند دیگری تغییر یافته است")

                # 🔒 LEVEL 4: Business Logic Validation
                if not fresh_vendor.is_active:
                    audit_logger.log_security_event(
                        'BALANCE_INCREASE_INACTIVE_VENDOR',
                        vendor.id,
                        {'amount': str(amount)},
                        'WARNING'
                    )
                    raise ValidationError("حساب فروشنده فعال نیست")

                # Check daily credits limit to prevent money laundering
                from django.utils import timezone
                today_credits = Transaction.objects.filter(
                    vendor=fresh_vendor,
                    transaction_type=TransactionType.CREDIT.value,
                    created_at__date=timezone.now().date(),
                    is_successful=True
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

                # Use vendor's daily_limit for credits operations as well
                if today_credits + amount > fresh_vendor.daily_limit:
                    audit_logger.log_security_event(
                        'CREDIT_DAILY_LIMIT_EXCEEDED',
                        vendor.id,
                        {
                            'today_credits': str(today_credits),
                            'vendor_daily_limit': str(fresh_vendor.daily_limit),
                            'requested': str(amount),
                            'would_exceed_by': str((today_credits + amount) - fresh_vendor.daily_limit)
                        },
                        'WARNING'
                    )
                    raise ValidationError(f"محدودیت روزانه افزایش اعتبار رعایت نشده. محدودیت: {fresh_vendor.daily_limit:,} تومان، افزایش امروز: {today_credits:,} تومان")

                # Store old balance for transaction record
                old_balance = fresh_vendor.balance
                new_balance = old_balance + amount

                # 🔒 LEVEL 5: Database Constraints Check
                if new_balance < Decimal('0'):
                    audit_logger.log_security_event(
                        'BALANCE_INCREASE_NEGATIVE_RESULT',
                        vendor.id,
                        {'old_balance': str(old_balance), 'amount': str(amount)},
                        'ERROR'
                    )
                    raise ValidationError("موجودی نتیجه منفی خواهد بود")

                # Atomic balance update with version increment
                updated_rows = Vendor.objects.filter(
                    id=fresh_vendor.id,
                    version=fresh_vendor.version
                ).update(
                    balance=F('balance') + amount,
                    version=F('version') + 1
                )

                if updated_rows == 0:
                    audit_logger.log_security_event(
                        'BALANCE_INCREASE_UPDATE_FAILED',
                        vendor.id,
                        {'amount': str(amount)},
                        'ERROR'
                    )
                    raise ValidationError("به‌روزرسانی موجودی ناموفق - تغییر همزمان شناسایی شد")

                fresh_vendor.refresh_from_db()

                # Create transaction record using centralized service
                transaction_obj = TransactionService.create_transaction_record(
                    vendor=fresh_vendor,
                    transaction_type=TransactionType.CREDIT.value,
                    amount=amount,
                    balance_before=old_balance,
                    balance_after=fresh_vendor.balance,
                    idempotency_key=idempotency_key,
                    credit_request=credit_request,
                    description=f"Credit increase: {amount}"
                )

                # 🔒 LEVEL 6: Update Idempotency Cache with Result
                result_data = {
                    'success': True,
                    'transaction_id': str(transaction_obj.id),
                    'vendor_id': vendor.id,
                    'old_balance': str(old_balance),
                    'new_balance': str(fresh_vendor.balance),
                    'completed_at': time.time()
                }
                idempotency_manager.update_operation_result(idempotency_key, result_data)

                # Update the original vendor object's balance and version
                vendor.balance = fresh_vendor.balance
                vendor.version = fresh_vendor.version

                audit_logger.log_transaction_attempt(
                    vendor.id, 'increase_balance', amount, True, None
                )

                logger.info(f"Balance increased successfully - Vendor: {vendor.id}, Amount: {amount}, New Balance: {fresh_vendor.balance}")
                return True, transaction_obj, "موجودی با موفقیت افزایش یافت"

        except Exception as e:
            logger.error(f"Error increasing balance for vendor {vendor.id}: {str(e)}")
            audit_logger.log_transaction_attempt(
                vendor.id, 'increase_balance', amount, False, str(e)
            )

            # Mark operation as failed in idempotency cache
            error_data = {
                'success': False,
                'error': str(e),
                'failed_at': time.time()
            }
            idempotency_manager.update_operation_result(idempotency_key, error_data)
            return False, None, f"خطا: {str(e)}"

        finally:
            lock_manager.release_lock(lock_key, lock_identifier)