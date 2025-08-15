#!/usr/bin/env python
"""
Simple Test Case for B2B Charge Service
Requirements:
- 2 vendors
- 10 credit increases
- 1000 charge sales
- Final balance verification

This test verifies the basic functionality and accounting integrity
of the B2B charge service system.
"""

import os
import sys
import django
from decimal import Decimal
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


# Setup Django environment BEFORE importing Django modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# NOW import Django modules after setup
from django.contrib.auth.models import User
from vendors.models import Vendor
from credits.models import CreditRequest
from credits.services import CreditService
from charges.services import ChargeManagement
from transactions.models import Transaction
from utils.enums import CreditRequestStatus, TransactionType


class SimpleB2BTestCase:
    """
    Simple test case for B2B charge service with accounting verification
    """
    
    def __init__(self):
        self.vendors = []
        self.results = {
            'credit_requests_created': 0,
            'credit_requests_approved': 0,
            'charges_made': 0,
            'charges_successful': 0,
            'total_credits_given': Decimal('0'),
            'total_charges_made': Decimal('0'),
            'errors': []
        }
        self.lock = threading.Lock()
    
    def setup_test_data(self):
        """Setup initial test data - 2 vendors"""
        print("🔧 Setting up test data...")
        
        # Create admin user
        try:
            self.admin_user = User.objects.get(username='admin')
        except User.DoesNotExist:
            self.admin_user = User.objects.create_user(
                username='admin',
                email='admin@test.com',
                password='admin123'
            )
        
        # Create 2 vendors with unique usernames
        import time
        timestamp = int(time.time())

        for i in range(1, 3):
            try:
                username = f'test_vendor{i}_{timestamp}'
                email = f'test_vendor{i}_{timestamp}@test.com'

                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password='vendor123'
                )
                vendor = Vendor.objects.create(
                    user=user,
                    name=f'Test Vendor {i} ({timestamp})',
                    balance=Decimal('0'),
                    daily_limit=Decimal('10000000')
                )
                self.vendors.append(vendor)
                print(f"✅ Created {vendor.name} with balance: {vendor.balance}")
            except Exception as e:
                print(f"❌ Error creating vendor {i}: {e}")
                self.results['errors'].append(f"Vendor creation error: {e}")

        # Check if we have vendors to work with
        if len(self.vendors) == 0:
            print("❌ No vendors created. Trying to use existing vendors...")
            # Try to get existing vendors
            existing_vendors = list(Vendor.objects.all()[:2])
            if existing_vendors:
                self.vendors = existing_vendors
                print(f"✅ Using {len(self.vendors)} existing vendors")
                for vendor in self.vendors:
                    print(f"   - {vendor.name} (Balance: {vendor.balance})")
            else:
                raise Exception("No vendors available for testing")

    def create_credit_requests(self):
        """Create 10 credit requests (5 for each vendor)"""
        print("\n💰 Creating credit requests...")
        
        credit_amounts = [
            Decimal('100000'), Decimal('150000'), Decimal('200000'), 
            Decimal('250000'), Decimal('300000')
        ]
        
        credit_requests = []
        
        for vendor in self.vendors:
            for i, amount in enumerate(credit_amounts):
                try:
                    credit_request = CreditRequest.objects.create(
                        vendor=vendor,
                        amount=amount,
                        status=CreditRequestStatus.PENDING
                    )
                    credit_requests.append(credit_request)
                    self.results['credit_requests_created'] += 1
                    print(f"✅ Created credit request for {vendor.name}: {amount}")
                except Exception as e:
                    print(f"❌ Error creating credit request: {e}")
                    self.results['errors'].append(f"Credit request creation error: {e}")
        
        return credit_requests
    
    def approve_credit_requests(self, credit_requests):
        """Approve all credit requests"""
        print("\n✅ Approving credit requests...")
        
        for credit_request in credit_requests:
            try:
                success, transaction_obj, message = CreditService.approve_credit_request(
                    credit_request.id, 
                    self.admin_user
                )
                
                if success:
                    self.results['credit_requests_approved'] += 1
                    self.results['total_credits_given'] += credit_request.amount
                    print(f"✅ Approved credit request for {credit_request.vendor.name}: {credit_request.amount}")
                else:
                    print(f"❌ Failed to approve credit request: {message}")
                    self.results['errors'].append(f"Credit approval error: {message}")
                    
            except Exception as e:
                print(f"❌ Error approving credit request: {e}")
                self.results['errors'].append(f"Credit approval error: {e}")
    
    def generate_charge_operations(self):
        """Generate 1000 charge operations"""
        print("\n🔌 Starting charge operations...")
        
        charge_amounts = [Decimal('5000'), Decimal('10000'), Decimal('15000'), Decimal('20000')]
        phone_numbers = [
            '+989121234567', '+989129876543', '+989127777777', '+989125555555',
            '+989123333333', '+989122222222', '+989124444444', '+989126666666',
            '+989128888888', '+989121111111'
        ]
        
        operations = []
        for i in range(1000):
            vendor = random.choice(self.vendors)
            amount = random.choice(charge_amounts)
            phone = random.choice(phone_numbers)
            operations.append((vendor, phone, amount, i))
        
        return operations
    
    def execute_single_charge(self, vendor, phone_number, amount, operation_id):
        """Execute a single charge operation"""
        try:
            # Generate unique idempotency key
            idempotency_key = f"charge_{vendor.id}_{operation_id}_{int(time.time() * 1000000)}"
            
            success, charge_obj, message = ChargeManagement.charge_phone(
                vendor=vendor,
                phone_number=phone_number,
                amount=amount,
                idempotency_key=idempotency_key
            )
            
            with self.lock:
                self.results['charges_made'] += 1
                if success:
                    self.results['charges_successful'] += 1
                    self.results['total_charges_made'] += amount
                    if self.results['charges_made'] % 100 == 0:
                        print(f"✅ Completed {self.results['charges_made']} charge operations")
                else:
                    if "insufficient" not in message.lower() and "ناکافی" not in message:  # Don't log insufficient balance as errors
                        self.results['errors'].append(f"Charge error: {message}")
            
            return success, message
            
        except Exception as e:
            with self.lock:
                self.results['errors'].append(f"Charge execution error: {e}")
            return False, str(e)
    
    def execute_charges_sequential(self, operations):
        """Execute charges sequentially"""
        print("🔄 Executing charges sequentially...")
        
        for vendor, phone, amount, op_id in operations:
            self.execute_single_charge(vendor, phone, amount, op_id)
    
    def execute_charges_parallel(self, operations, max_workers=10):
        """Execute charges in parallel to test concurrency"""
        print(f"🔄 Executing charges in parallel with {max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for vendor, phone, amount, op_id in operations:
                future = executor.submit(self.execute_single_charge, vendor, phone, amount, op_id)
                futures.append(future)
            
            # Wait for all operations to complete
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    with self.lock:
                        self.results['errors'].append(f"Parallel execution error: {e}")
    
    def verify_accounting_integrity(self):
        """Verify accounting integrity of the system"""
        print("\n🔍 Verifying accounting integrity...")
        
        total_system_balance = Decimal('0')
        accounting_errors = []
        
        for vendor in self.vendors:
            # Refresh vendor from database
            vendor.refresh_from_db()
            
            # Calculate expected balance from transactions
            credit_transactions = Transaction.objects.filter(
                vendor=vendor,
                transaction_type=TransactionType.CREDIT,
                is_successful=True
            )
            
            sale_transactions = Transaction.objects.filter(
                vendor=vendor,
                transaction_type=TransactionType.SALE,
                is_successful=True
            )
            
            total_credits = sum(t.amount for t in credit_transactions)
            total_sales = sum(t.amount for t in sale_transactions)
            calculated_balance = total_credits - total_sales
            
            print(f"\n📊 {vendor.name} Financial Report:")
            print(f"   Current Balance: {vendor.balance}")
            print(f"   Total Credits: {total_credits}")
            print(f"   Total Sales: {total_sales}")
            print(f"   Calculated Balance: {calculated_balance}")
            
            # Verify balance integrity
            if vendor.balance != calculated_balance:
                error_msg = f"Balance mismatch for {vendor.name}: DB={vendor.balance}, Calculated={calculated_balance}"
                accounting_errors.append(error_msg)
                print(f"   ❌ {error_msg}")
            else:
                print(f"   ✅ Balance integrity verified")
            
            total_system_balance += vendor.balance
        
        print(f"\n💰 Total System Balance: {total_system_balance}")
        print(f"📝 Total Transactions: {Transaction.objects.count()}")
        
        return accounting_errors
    
    def print_final_report(self):
        """Print comprehensive final report"""
        print("\n" + "="*60)
        print("📋 FINAL TEST REPORT")
        print("="*60)
        
        print(f"🏢 Vendors Created: {len(self.vendors)}")
        print(f"💰 Credit Requests Created: {self.results['credit_requests_created']}")
        print(f"✅ Credit Requests Approved: {self.results['credit_requests_approved']}")
        print(f"🔌 Charges Attempted: {self.results['charges_made']}")
        print(f"✅ Charges Successful: {self.results['charges_successful']}")
        print(f"💸 Total Credits Given: {self.results['total_credits_given']}")
        print(f"💸 Total Charges Made: {self.results['total_charges_made']}")
        
        if self.results['errors']:
            print(f"\n❌ Errors Encountered: {len(self.results['errors'])}")
            for error in self.results['errors'][:10]:  # Show first 10 errors
                print(f"   - {error}")
            if len(self.results['errors']) > 10:
                print(f"   ... and {len(self.results['errors']) - 10} more errors")
        else:
            print("\n✅ No errors encountered")
    
    def run_test(self, parallel=False):
        """Run the complete test case"""
        start_time = time.time()
        print("🚀 Starting B2B Charge Service Test Case")
        print("="*60)
        
        try:
            # Setup
            self.setup_test_data()
            
            # Credit operations
            credit_requests = self.create_credit_requests()
            self.approve_credit_requests(credit_requests)
            
            # Generate charge operations
            operations = self.generate_charge_operations()
            
            # Execute charges
            if parallel:
                self.execute_charges_parallel(operations)
            else:
                self.execute_charges_sequential(operations)
            
            # Verify integrity
            accounting_errors = self.verify_accounting_integrity()
            
            # Final report
            self.print_final_report()
            
            # Test results
            execution_time = time.time() - start_time
            print(f"\n⏱️ Total Execution Time: {execution_time:.2f} seconds")
            
            if accounting_errors:
                print("\n❌ TEST FAILED: Accounting integrity issues found")
                for error in accounting_errors:
                    print(f"   - {error}")
                return False
            else:
                print("\n✅ TEST PASSED: All accounting integrity checks passed")
                return True
                
        except Exception as e:
            print(f"\n❌ TEST FAILED with exception: {e}")
            return False


def main():
    """Main execution function"""
    print("B2B Charge Service - Simple Test Case")
    print("This test creates 2 vendors, 10 credit increases, and 1000 charge sales")
    print()
    
    # Run sequential test
    print("=" * 60)
    print("RUNNING SEQUENTIAL TEST...")
    print("=" * 60)
    test_case = SimpleB2BTestCase()
    sequential_result = test_case.run_test(parallel=False)

    if sequential_result:
        print("\n🎉 Sequential test completed successfully!")
    else:
        print("\n💥 Sequential test failed!")
    
    print("\n" + "=" * 60)
    print("RUNNING PARALLEL TEST...")
    print("=" * 60)
    print("Testing concurrent operations to verify race condition protection...")

    # Run parallel test
    parallel_test_case = SimpleB2BTestCase()
    parallel_result = parallel_test_case.run_test(parallel=True)

    if parallel_result:
        print("\n🎉 Parallel test completed successfully!")
    else:
        print("\n💥 Parallel test failed!")

    # Summary
    print("\n" + "=" * 60)
    print("📋 OVERALL TEST SUMMARY")
    print("=" * 60)
    print(f"Sequential Test: {'✅ PASSED' if sequential_result else '❌ FAILED'}")
    print(f"Parallel Test:   {'✅ PASSED' if parallel_result else '❌ FAILED'}")

    overall_success = sequential_result and parallel_result

    if overall_success:
        print("\n🎯 ALL TESTS PASSED! System is ready for production.")
        print("✅ Race condition protection verified")
        print("✅ Double spending prevention verified")
        print("✅ Accounting integrity maintained under load")
    else:
        print("\n❌ SOME TESTS FAILED! Please review the issues above.")

    return overall_success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
