from django.db import models, connection
from django.db.models import Sum, Case, When, F, Count
from typing import Dict, List, Optional
from decimal import Decimal
import logging
import time
from datetime import datetime

from .models import Transaction
from utils.enums import TransactionType, TransactionStatus
from utils.security_managers import SecurityAuditLogger

logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class TransactionService:
    """
    Core transaction service - responsible only for transaction creation and logging
    All business logic validation should be done in respective service layers
    """

    @staticmethod
    def create_transaction_record(
        vendor,
        transaction_type: int,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        idempotency_key: str,
        phone_number: str = None,
        credit_request = None,
        description: str = None
    ) -> Transaction:
        """
        Create a transaction record with all required fields
        This is the single source of truth for transaction creation
        """
        return Transaction.objects.create(
            vendor=vendor,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            phone_number=phone_number,
            credit_request=credit_request,
            idempotency_key=idempotency_key,
            status=TransactionStatus.APPROVED.value,
            is_successful=True,
            description=description or f"Transaction: {amount}"
        )

    @staticmethod
    def get_vendor_transactions(
        vendor_id,
        transaction_type=None,
        start_date=None,
        end_date=None,
        limit=None
    ):
        """Get transactions for a vendor with filtering"""
        query = Transaction.objects.filter(vendor_id=vendor_id)

        if transaction_type:
            query = query.filter(transaction_type=transaction_type)
        if start_date:
            query = query.filter(created_at__gte=start_date)
        if end_date:
            query = query.filter(created_at__lte=end_date)

        query = query.order_by('-created_at')

        if limit:
            query = query[:limit]

        return query

    @staticmethod
    def get_transaction_summary(vendor_id, date_range=None) -> Dict:
        """Get transaction summary for a vendor"""
        base_query = Transaction.objects.filter(
            vendor_id=vendor_id,
            is_successful=True
        )

        if date_range:
            base_query = base_query.filter(created_at__range=date_range)

        summary = base_query.aggregate(
            total_credits=Sum(
                Case(When(transaction_type=TransactionType.CREDIT.value, then='amount'),
                     default=Decimal('0'))
            ),
            total_sales=Sum(
                Case(When(transaction_type=TransactionType.SALE.value, then='amount'),
                     default=Decimal('0'))
            ),
            credit_count=Sum(
                Case(When(transaction_type=TransactionType.CREDIT.value, then=1),
                     default=0)
            ),
            sale_count=Sum(
                Case(When(transaction_type=TransactionType.SALE.value, then=1),
                     default=0)
            )
        )

        return {
            'credits': {
                'total': str(summary['total_credits'] or Decimal('0')),
                'count': summary['credit_count'] or 0
            },
            'sales': {
                'total': str(summary['total_sales'] or Decimal('0')),
                'count': summary['sale_count'] or 0
            },
            'net_balance': str((summary['total_credits'] or Decimal('0')) - (summary['total_sales'] or Decimal('0')))
        }

    @staticmethod
    def create_pending_transaction(
        vendor,
        transaction_type: int,
        amount: Decimal,
        idempotency_key: str,
        phone_number: str = None,
        credit_request = None,
        description: str = None
    ) -> Transaction:
        """Create a pending transaction record"""
        return Transaction.objects.create(
            vendor=vendor,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=vendor.balance,
            balance_after=vendor.balance,  # Will be updated when approved
            phone_number=phone_number,
            credit_request=credit_request,
            idempotency_key=idempotency_key,
            status=TransactionStatus.PENDING.value,
            is_successful=False,
            description=description or f"Pending {transaction_type}: {amount}"
        )

    @staticmethod
    def update_transaction_status(
        transaction_id,
        status: int,
        balance_after: Decimal = None,
        is_successful: bool = None,
        description: str = None
    ):
        """Update transaction status and related fields"""
        update_fields = {'status': status}

        if balance_after is not None:
            update_fields['balance_after'] = balance_after
        if is_successful is not None:
            update_fields['is_successful'] = is_successful
        if description is not None:
            update_fields['description'] = description

        Transaction.objects.filter(id=transaction_id).update(**update_fields)



class BalanceReconciliationService:
    """Enhanced Balance Reconciliation Service برای اطمینان از همخوانی سیستم حسابداری"""

    @staticmethod
    def calculated_balance(vendor) -> Decimal:
        """
        محاسبه موجودی بر اساس تراکنش‌ها (برای reconciliation و audit)
        """
        agg = Transaction.objects.filter(
            vendor=vendor,
            is_successful=True
        ).aggregate(
            b=Sum(
                Case(
                    When(transaction_type=TransactionType.CREDIT.value, then='amount'),
                    When(transaction_type=TransactionType.SALE.value, then=F('amount') * -1),
                    output_field=models.DecimalField(max_digits=18, decimal_places=2)
                )
            )
        )
        return agg['b'] or Decimal('0.00')

    @staticmethod
    def balance_reconciliation(vendor) -> Dict:
        """
        مقایسه موجودی ذخیره شده با موجودی محاسبه شده
        """
        calculated = BalanceReconciliationService.calculated_balance(vendor)
        stored = vendor.balance
        difference = stored - calculated
        is_consistent = abs(difference) < Decimal('0.01')  # tolerance برای rounding

        # آمار تراکنش‌ها
        transaction_stats = Transaction.objects.filter(
            vendor=vendor,
            is_successful=True
        ).aggregate(
            credit_total=Sum(
                Case(When(transaction_type=TransactionType.CREDIT.value, then='amount'),
                     default=Decimal('0'))
            ),
            sale_total=Sum(
                Case(When(transaction_type=TransactionType.SALE.value, then='amount'),
                     default=Decimal('0'))
            ),
            credit_count=Count(
                Case(When(transaction_type=TransactionType.CREDIT.value, then=1))
            ),
            sale_count=Count(
                Case(When(transaction_type=TransactionType.SALE.value, then=1))
            )
        )

        reconciliation = {
            'vendor_id': vendor.id,
            'vendor_name': vendor.name,
            'stored_balance': stored,
            'calculated_balance': calculated,
            'difference': difference,
            'is_consistent': is_consistent,
            'transaction_summary': {
                'total_credits': transaction_stats['credit_total'] or Decimal('0'),
                'total_sales': transaction_stats['sale_total'] or Decimal('0'),
                'credit_transactions_count': transaction_stats['credit_count'] or 0,
                'sale_transactions_count': transaction_stats['sale_count'] or 0
            },
            'checked_at': time.time()
        }

        if not is_consistent:
            audit_logger.log_security_event(
                'BALANCE_INCONSISTENCY_DETECTED',
                vendor.id,
                {
                    'stored_balance': str(stored),
                    'calculated_balance': str(calculated),
                    'difference': str(difference),
                    'vendor_name': vendor.name
                },
                'ERROR'
            )
            logger.error(f"Balance inconsistency for vendor {vendor.id}: "
                        f"stored={stored}, calculated={calculated}, diff={difference}")
        else:
            logger.info(f"Balance verified for vendor {vendor.id}: {stored}")

        return reconciliation

    @staticmethod
    def reconcile_all_balances() -> Dict:
        """
        Reconciliation تمام فروشندگان
        """
        from vendors.models import Vendor
        
        start_time = time.time()
        results = []
        vendors = Vendor.objects.all()

        for vendor in vendors:
            reconciliation = BalanceReconciliationService.balance_reconciliation(vendor)
            results.append(reconciliation)

        # محاسبه آمار کلی
        total_vendors = len(vendors)
        consistent_vendors = sum(1 for r in results if r['is_consistent'])
        inconsistent_vendors = total_vendors - consistent_vendors
        total_difference = sum(abs(r['difference']) for r in results if not r['is_consistent'])

        # آمار سیستم
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as transaction_count,
                       SUM(CASE WHEN transaction_type = %s AND is_successful = true THEN amount ELSE 0 END) as total_credits,
                       SUM(CASE WHEN transaction_type = %s AND is_successful = true THEN amount ELSE 0 END) as total_sales
                FROM transactions_transaction
            """, [TransactionType.CREDIT.value, TransactionType.SALE.value])
            row = cursor.fetchone()
            system_stats = {
                'total_transactions': row[0] or 0,
                'total_credits': row[1] or Decimal('0'),
                'total_sales': row[2] or Decimal('0'),
                'net_system_balance': (row[1] or Decimal('0')) - (row[2] or Decimal('0'))
            }

        end_time = time.time()

        summary = {
            'execution_time': end_time - start_time,
            'total_vendors': total_vendors,
            'consistent_vendors': consistent_vendors,
            'inconsistent_vendors': inconsistent_vendors,
            'consistency_percentage': (consistent_vendors / total_vendors * 100) if total_vendors > 0 else 0,
            'total_difference': total_difference,
            'system_stats': system_stats,
            'checked_at': datetime.now().isoformat()
        }

        # لاگ نتیجه کلی
        audit_logger.log_security_event(
            'SYSTEM_BALANCE_RECONCILIATION_COMPLETED',
            None,
            {
                'total_vendors': total_vendors,
                'consistent_vendors': consistent_vendors,
                'inconsistent_vendors': inconsistent_vendors,
                'execution_time': end_time - start_time
            },
            'INFO' if inconsistent_vendors == 0 else 'WARNING'
        )

        return {
            'summary': summary,
            'vendor_results': results
        }

    @staticmethod
    def generate_reconciliation_report(vendor_id: int = None) -> str:
        """
        تولید گزارش تفصیلی reconciliation
        """
        if vendor_id:
            from vendors.models import Vendor
            try:
                vendor = Vendor.objects.get(id=vendor_id)
                result = BalanceReconciliationService.balance_reconciliation(vendor)
                results = {'vendor_results': [result]}
            except Vendor.DoesNotExist:
                return f"خطا: فروشنده با شناسه {vendor_id} یافت نشد"
        else:
            results = BalanceReconciliationService.reconcile_all_balances()

        report = "=" * 80 + "\n"
        report += "           گزارش همخوانی سیستم حسابداری\n"
        report += "=" * 80 + "\n\n"

        if 'summary' in results:
            summary = results['summary']
            report += f"📊 خلاصه کلی:\n"
            report += f"  • تعداد کل فروشندگان: {summary['total_vendors']}\n"
            report += f"  • فروشندگان سازگار: {summary['consistent_vendors']} ({summary['consistency_percentage']:.1f}%)\n"
            report += f"  • فروشندگان ناسازگار: {summary['inconsistent_vendors']}\n"
            report += f"  • مجموع اختلاف: {summary['total_difference']:,} تومان\n"
            report += f"  • زمان اجرا: {summary['execution_time']:.2f} ثانیه\n"
            report += f"  • تاریخ بررسی: {summary['checked_at']}\n\n"

            stats = summary['system_stats']
            report += f"📈 آمار سیستم:\n"
            report += f"  • کل تراکنش‌ها: {stats['total_transactions']:,}\n"
            report += f"  • کل کردیت‌ها: {stats['total_credits']:,} تومان\n"
            report += f"  • کل فروش‌ها: {stats['total_sales']:,} تومان\n"
            report += f"  • موجودی خالص سیستم: {stats['net_system_balance']:,} تومان\n\n"

        report += "📋 جزئیات فروشندگان:\n"
        report += "-" * 80 + "\n"

        for vendor_result in results['vendor_results']:
            vendor_id = vendor_result['vendor_id']
            vendor_name = vendor_result['vendor_name']
            stored = vendor_result['stored_balance']
            calculated = vendor_result['calculated_balance']
            difference = vendor_result['difference']
            is_consistent = vendor_result['is_consistent']
            summary = vendor_result['transaction_summary']

            status_icon = "✅" if is_consistent else "❌"
            status_text = "سازگار" if is_consistent else "ناسازگار"

            report += f"{status_icon} فروشنده {vendor_id} ({vendor_name}): {status_text}\n"
            report += f"     موجودی فعلی: {stored:,} تومان\n"
            report += f"     موجودی محاسبه شده: {calculated:,} تومان\n"

            if not is_consistent:
                report += f"     ❗ اختلاف: {difference:,} تومان\n"

            report += f"     کردیت‌ها: {summary['total_credits']:,} تومان ({summary['credit_transactions_count']} تراکنش)\n"
            report += f"     فروش‌ها: {summary['total_sales']:,} تومان ({summary['sale_transactions_count']} تراکنش)\n"
            report += "-" * 40 + "\n"

        report += "\n" + "=" * 80 + "\n"
        report += "پایان گزارش\n"

        return report

