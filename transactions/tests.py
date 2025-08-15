"""
Test Cases for Balance Reconciliation in transactions app
"""

import os
import sys
import django
from django.conf import settings

# Django setup before importing models
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

import unittest
from decimal import Decimal
from django.test import TestCase
from vendors.models import Vendor
from transactions.services import BalanceReconciliationService
from utils.enums import TransactionType
from charges.services import ChargeManagement
from credits.services import CreditManagement
import threading
import time
import random


class TransactionsBalanceReconciliationTestCase(TestCase):
    """
    Test cases for accounting reconciliation in transactions app
    """

    def setUp(self):
        """Create test data"""
        from django.contrib.auth.models import User

        # Create users for vendors
        user1 = User.objects.create_user(
            username='vendor1_user',
            email='vendor1@example.com',
            password='testpass123'
        )

        user2 = User.objects.create_user(
            username='vendor2_user',
            email='vendor2@example.com',
            password='testpass123'
        )

        self.vendor1 = Vendor.objects.create(
            user=user1,
            name="First Vendor",
            balance=Decimal('0'),
            daily_limit=Decimal('10000000'),  # 10 million
            is_active=True
        )

        self.vendor2 = Vendor.objects.create(
            user=user2,
            name="Second Vendor",
            balance=Decimal('0'),
            daily_limit=Decimal('5000000'),   # 5 million
            is_active=True
        )

    def test_balance_reconciliation_service_basic(self):
        """
        Basic test for BalanceReconciliationService
        """
        print("\n=== Testing Balance Reconciliation Service ===")

        # Credit increase
        credit_amount = Decimal('1000000')  # 1M
        CreditManagement.increase_balance(self.vendor1, credit_amount)

        # Charge sale
        charge_amount = Decimal('50000')    # 50K
        ChargeManagement.charge_phone(self.vendor1, "09123456789", charge_amount)

        # Check reconciliation
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
        Test calculated_balance method
        """
        print("\n=== Testing Calculated Balance Method ===")

        # Various transactions
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

        # Calculate balance using service
        calculated = BalanceReconciliationService.calculated_balance(self.vendor2)

        print(f"Expected: {expected_balance:,}")
        print(f"Calculated: {calculated:,}")
        print(f"Vendor DB Balance: {self.vendor2.balance:,}")

        # Verification
        self.vendor2.refresh_from_db()
        self.assertEqual(calculated, expected_balance)
        self.assertEqual(self.vendor2.balance, expected_balance)

        print("✅ Calculated Balance Method Test PASSED!")

    def test_reconcile_all_balances(self):
        """
        Test reconcile_all_balances for multiple vendors
        """
        print("\n=== Testing Reconcile All Balances ===")

        # Transaction for vendor1
        CreditManagement.increase_balance(self.vendor1, Decimal('2000000'))
        ChargeManagement.charge_phone(self.vendor1, "09111111111", Decimal('500000'))

        # Transaction for vendor2
        CreditManagement.increase_balance(self.vendor2, Decimal('1500000'))
        ChargeManagement.charge_phone(self.vendor2, "09222222222", Decimal('300000'))

        # Check all vendors
        results = BalanceReconciliationService.reconcile_all_balances()

        # Check summary
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

        # Check system stats
        stats = summary['system_stats']
        self.assertEqual(stats['total_credits'], Decimal('3500000'))  # 2M + 1.5M
        self.assertEqual(stats['total_sales'], Decimal('800000'))     # 500K + 300K
        self.assertEqual(stats['net_system_balance'], Decimal('2700000'))

        print("✅ Reconcile All Balances Test PASSED!")

    def test_report_generation(self):
        """
        Test report generation
        """
        print("\n=== Testing Report Generation ===")

        # Create transactions
        CreditManagement.increase_balance(self.vendor1, Decimal('1000000'))
        ChargeManagement.charge_phone(self.vendor1, "09123456789", Decimal('250000'))

        # Generate report for specific vendor
        report_single = BalanceReconciliationService.generate_reconciliation_report(self.vendor1.id)

        # Check report content
        self.assertIn("Balance Reconciliation Report", report_single)
        self.assertIn(f"Vendor {self.vendor1.id}", report_single)
        self.assertIn("Consistent", report_single)
        self.assertIn("750,000", report_single)  # Remaining balance

        # Generate general report
        report_all = BalanceReconciliationService.generate_reconciliation_report()

        self.assertIn("Overall Summary", report_all)
        self.assertIn("System Statistics", report_all)

        print(f"Single Report Length: {len(report_single)} chars")
        print(f"All Report Length: {len(report_all)} chars")
        print("✅ Report Generation Test PASSED!")

    def test_concurrent_transactions_consistency(self):
        """
        Test consistency under concurrent transactions
        """
        print("\n=== Testing Concurrent Transactions Consistency ===")

        # Initial credit
        initial_amount = Decimal('5000000')  # 5M
        CreditManagement.increase_balance(self.vendor1, initial_amount)

        # Lists to store results
        successful_charges = []
        errors = []

        def charge_worker(start_idx, count):
            """Worker for concurrent charging"""
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

                    time.sleep(random.uniform(0.001, 0.005))  # Short delay

                except Exception as e:
                    errors.append(str(e))

        # Create threads
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

        # Wait for completion
        for thread in threads:
            thread.join()

        end_time = time.time()

        # Analyze results
        total_successful = len(successful_charges)
        total_errors = len(errors)
        total_charged = sum(successful_charges)

        print(f"Execution Time: {end_time - start_time:.2f}s")
        print(f"Successful Charges: {total_successful}")
        print(f"Total Errors: {total_errors}")
        print(f"Total Charged Amount: {total_charged:,}")

        # Final reconciliation check
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
        Performance test with high volume transactions
        """
        print("\n=== Testing Large Volume Reconciliation ===")

        # High volume transactions
        total_credits = Decimal('0')
        total_sales = Decimal('0')

        start_time = time.time()

        # 20 credits
        for i in range(20):
            amount = Decimal(f"{(i+1)*10000}")  # 10K, 20K, 30K, ...
            CreditManagement.increase_balance(self.vendor1, amount)
            total_credits += amount

        # 100 sales
        for i in range(100):
            amount = Decimal('5000')  # 5K each
            phone = f"091234{i:04d}"
            success, _, _ = ChargeManagement.charge_phone(self.vendor1, phone, amount)
            if success:
                total_sales += amount

        transaction_time = time.time() - start_time

        # Check reconciliation
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

        # Performance assertion - ensure reconciliation is fast
        self.assertLess(reconciliation_time, 1.0)  # Less than 1 second

        print("✅ Large Volume Reconciliation Test PASSED!")

    def tearDown(self):
        """Cleanup"""
        # Django TestCase automatically performs rollback
        pass


if __name__ == '__main__':
    unittest.main()
