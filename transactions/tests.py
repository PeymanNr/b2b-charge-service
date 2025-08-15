"""
Test Cases برای Balance Reconciliation در اپ transactions
"""

import unittest
from decimal import Decimal
from django.test import TestCase
from django.db import transaction
from vendors.models import Vendor
from transactions.models import Transaction
from transactions.services import BalanceReconciliationService
from credits.models import CreditRequest
from charges.models import Charge
from utils.enums import TransactionType, CreditRequestStatus
from charges.services import ChargeManagement
from credits.services import CreditService, CreditManagement
import threading
import time
import random


class TransactionsBalanceReconciliationTestCase(TestCase):
    """
    تست همخوانی حسابداری در اپ transactions
    """

    def setUp(self):
        """ایجاد داده‌های تست"""
        self.vendor1 = Vendor.objects.create(
            name="فروشنده اول",
            phone="09123456789",
            balance=Decimal('0'),
            daily_limit=Decimal('10000000'),  # 10 میلیون
            is_active=True
        )

        self.vendor2 = Vendor.objects.create(
            name="فروشنده دوم",
            phone="09987654321",
            balance=Decimal('0'),
            daily_limit=Decimal('5000000'),   # 5 میلیون
            is_active=True
        )

    def test_balance_reconciliation_service_basic(self):
        """
        تست اصلی BalanceReconciliationService
        """
        print("\n=== Testing Balance Reconciliation Service ===")

        # افزایش اعتبار
        credit_amount = Decimal('1000000')  # 1M
        CreditManagement.increase_balance(self.vendor1, credit_amount)

        # فروش شارژ
        charge_amount = Decimal('50000')    # 50K
        ChargeManagement.charge_phone(self.vendor1, "09123456789", charge_amount)

        # بررسی همخوانی
        result = BalanceReconciliationService.balance_reconciliation(self.vendor1)

        print(f"Stored Balance: {result['stored_balance']:,}")
        print(f"Calculated Balance: {result['calculated_balance']:,}")
        print(f"Is Consistent: {result['is_consistent']}")

        # Assertions
        self.assertTrue(result['is_consistent'])
        self.assertEqual(result['stored_balance'], Decimal('950000'))
        self.assertEqual(result['calculated_balance'], Decimal('950000'))
        self.assertEqual(result['difference'], Decimal('0'))

        print("✅ Basic Balance Reconciliation Test PASSED!")

    def test_calculated_balance_method(self):
        """
        تست متد calculated_balance
        """
        print("\n=== Testing Calculated Balance Method ===")

        # تراکنش‌های مختلف
        amounts = [
            (TransactionType.CREDIT, Decimal('500000')),
            (TransactionType.CREDIT, Decimal('300000')),
            (TransactionType.SALE, Decimal('100000')),
            (TransactionType.SALE, Decimal('75000')),
            (TransactionType.CREDIT, Decimal('200000'))
        ]

        expected_balance = Decimal('0')

        for tx_type, amount in amounts:
            if tx_type == TransactionType.CREDIT:
                CreditManagement.increase_balance(self.vendor2, amount)
                expected_balance += amount
            else:  # SALE
                ChargeManagement.charge_phone(self.vendor2, f"091234{amount}", amount)
                expected_balance -= amount

        # محاسبه موجودی با service
        calculated = BalanceReconciliationService.calculated_balance(self.vendor2)

        print(f"Expected: {expected_balance:,}")
        print(f"Calculated: {calculated:,}")
        print(f"Vendor DB Balance: {self.vendor2.balance:,}")

        # بررسی
        self.vendor2.refresh_from_db()
        self.assertEqual(calculated, expected_balance)
        self.assertEqual(self.vendor2.balance, expected_balance)

        print("✅ Calculated Balance Method Test PASSED!")

    def test_reconcile_all_balances(self):
        """
        تست reconcile_all_balances برای چند فروشنده
        """
        print("\n=== Testing Reconcile All Balances ===")

        # تراکنش برای vendor1
        CreditManagement.increase_balance(self.vendor1, Decimal('2000000'))
        ChargeManagement.charge_phone(self.vendor1, "09111111111", Decimal('500000'))

        # تراکنش برای vendor2
        CreditManagement.increase_balance(self.vendor2, Decimal('1500000'))
        ChargeManagement.charge_phone(self.vendor2, "09222222222", Decimal('300000'))

        # بررسی همه
        results = BalanceReconciliationService.reconcile_all_balances()

        # بررسی summary
        summary = results['summary']
        print(f"Total Vendors: {summary['total_vendors']}")
        print(f"Consistent: {summary['consistent_vendors']}")
        print(f"Inconsistent: {summary['inconsistent_vendors']}")
        print(f"Consistency %: {summary['consistency_percentage']:.1f}%")

        # Assertions
        self.assertEqual(summary['total_vendors'], 2)
        self.assertEqual(summary['consistent_vendors'], 2)
        self.assertEqual(summary['inconsistent_vendors'], 0)
        self.assertEqual(summary['consistency_percentage'], 100.0)

        # بررسی system stats
        stats = summary['system_stats']
        self.assertEqual(stats['total_credits'], Decimal('3500000'))  # 2M + 1.5M
        self.assertEqual(stats['total_sales'], Decimal('800000'))     # 500K + 300K
        self.assertEqual(stats['net_system_balance'], Decimal('2700000'))

        print("✅ Reconcile All Balances Test PASSED!")

    def test_report_generation(self):
        """
        تست تولید گزارش
        """
        print("\n=== Testing Report Generation ===")

        # ایجاد تراکنش‌ها
        CreditManagement.increase_balance(self.vendor1, Decimal('1000000'))
        ChargeManagement.charge_phone(self.vendor1, "09123456789", Decimal('250000'))

        # تولید گزارش برای vendor خاص
        report_single = BalanceReconciliationService.generate_reconciliation_report(self.vendor1.id)

        # بررسی محتوای گزارش
        self.assertIn("گزارش همخوانی سیستم حسابداری", report_single)
        self.assertIn(f"فروشنده {self.vendor1.id}", report_single)
        self.assertIn("سازگار", report_single)
        self.assertIn("750,000", report_single)  # موجودی باقیمانده

        # تولید گزارش کلی
        report_all = BalanceReconciliationService.generate_reconciliation_report()

        self.assertIn("خلاصه کلی", report_all)
        self.assertIn("آمار سیستم", report_all)

        print(f"Single Report Length: {len(report_single)} chars")
        print(f"All Report Length: {len(report_all)} chars")
        print("✅ Report Generation Test PASSED!")

    def test_concurrent_transactions_consistency(self):
        """
        تست همخوانی تحت تراکنش‌های موازی
        """
        print("\n=== Testing Concurrent Transactions Consistency ===")

        # اعتبار اولیه
        initial_amount = Decimal('5000000')  # 5M
        CreditManagement.increase_balance(self.vendor1, initial_amount)

        # لیست برای ذخیره نتایج
        successful_charges = []
        errors = []

        def charge_worker(start_idx, count):
            """Worker برای شارژ موازی"""
            for i in range(count):
                try:
                    phone = f"091234{start_idx:02d}{i:02d}"
                    charge_amount = Decimal('10000')  # 10K

                    success, _, message = ChargeManagement.charge_phone(
                        self.vendor1, phone, charge_amount
                    )

                    if success:
                        successful_charges.append(charge_amount)
                    else:
                        errors.append(message)

                    time.sleep(random.uniform(0.001, 0.005))  # تاخیر کوتاه

                except Exception as e:
                    errors.append(str(e))

        # ایجاد threads
        threads = []
        charges_per_thread = 50
        num_threads = 4

        start_time = time.time()

        for i in range(num_threads):
            thread = threading.Thread(
                target=charge_worker,
                args=(i, charges_per_thread)
            )
            threads.append(thread)
            thread.start()

        # انتظار برای تکمیل
        for thread in threads:
            thread.join()

        end_time = time.time()

        # تحلیل نتایج
        total_successful = len(successful_charges)
        total_errors = len(errors)
        total_charged = sum(successful_charges)

        print(f"Execution Time: {end_time - start_time:.2f}s")
        print(f"Successful Charges: {total_successful}")
        print(f"Total Errors: {total_errors}")
        print(f"Total Charged Amount: {total_charged:,}")

        # بررسی همخوانی نهایی
        self.vendor1.refresh_from_db()
        reconciliation = BalanceReconciliationService.balance_reconciliation(self.vendor1)

        expected_final_balance = initial_amount - total_charged

        print(f"Expected Final Balance: {expected_final_balance:,}")
        print(f"Actual Final Balance: {self.vendor1.balance:,}")
        print(f"Is Consistent: {reconciliation['is_consistent']}")

        # Assertions
        self.assertTrue(reconciliation['is_consistent'])
        self.assertEqual(self.vendor1.balance, expected_final_balance)

        print("✅ Concurrent Transactions Consistency Test PASSED!")

    def test_large_volume_reconciliation(self):
        """
        تست performance با حجم بالای تراکنش
        """
        print("\n=== Testing Large Volume Reconciliation ===")

        # تراکنش‌های زیاد
        total_credits = Decimal('0')
        total_sales = Decimal('0')

        start_time = time.time()

        # 20 کردیت
        for i in range(20):
            amount = Decimal(f"{(i+1)*10000}")  # 10K, 20K, 30K, ...
            CreditManagement.increase_balance(self.vendor1, amount)
            total_credits += amount

        # 100 فروش
        for i in range(100):
            amount = Decimal('5000')  # 5K هرکدام
            phone = f"091234{i:04d}"
            success, _, _ = ChargeManagement.charge_phone(self.vendor1, phone, amount)
            if success:
                total_sales += amount

        transaction_time = time.time() - start_time

        # بررسی همخوانی
        reconciliation_start = time.time()
        result = BalanceReconciliationService.balance_reconciliation(self.vendor1)
        reconciliation_time = time.time() - reconciliation_start

        expected_balance = total_credits - total_sales

        print(f"Transaction Creation Time: {transaction_time:.2f}s")
        print(f"Reconciliation Time: {reconciliation_time:.2f}s")
        print(f"Total Credits: {total_credits:,}")
        print(f"Total Sales: {total_sales:,}")
        print(f"Expected Balance: {expected_balance:,}")
        print(f"Actual Balance: {self.vendor1.balance:,}")
        print(f"Transaction Count: {result['transaction_summary']['credit_transactions_count'] + result['transaction_summary']['sale_transactions_count']}")

        # Assertions
        self.assertTrue(result['is_consistent'])
        self.assertEqual(result['stored_balance'], expected_balance)
        self.assertEqual(result['calculated_balance'], expected_balance)

        # Performance assertion - بررسی اینکه reconciliation سریع باشد
        self.assertLess(reconciliation_time, 1.0)  # کمتر از 1 ثانیه

        print("✅ Large Volume Reconciliation Test PASSED!")

    def tearDown(self):
        """پاکسازی"""
        # Django TestCase خودکار rollback می‌کند
        pass


if __name__ == '__main__':
    unittest.main()
