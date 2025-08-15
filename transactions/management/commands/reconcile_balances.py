"""
Django Management Command for checking accounting system consistency
Usage: python manage.py reconcile_balances [--vendor-id=123] [--report]
"""

from django.core.management.base import BaseCommand
from transactions.services import BalanceReconciliationService
from vendors.models import Vendor
import time


class Command(BaseCommand):
    help = 'Check balance consistency for vendors'

    def add_arguments(self, parser):
        parser.add_argument(
            '--vendor-id',
            type=int,
            help='Check specific vendor',
        )
        parser.add_argument(
            '--report',
            action='store_true',
            help='Save report to file',
        )

    def handle(self, *args, **options):
        vendor_id = options.get('vendor_id')
        generate_report = options.get('report', False)

        self.stdout.write(self.style.SUCCESS("🔄 Starting accounting system consistency check..."))
        start_time = time.time()

        if vendor_id:
            self.handle_single_vendor(vendor_id)
        else:
            self.handle_all_vendors()

        if generate_report:
            self.generate_report_file(vendor_id)

        end_time = time.time()
        self.stdout.write(
            self.style.SUCCESS(f"✅ Check completed in {end_time - start_time:.2f} seconds")
        )

    def handle_single_vendor(self, vendor_id):
        """Check single vendor"""
        try:
            vendor = Vendor.objects.get(id=vendor_id)
            result = BalanceReconciliationService.balance_reconciliation(vendor)
            
            self.display_vendor_result(result)
            
        except Vendor.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"❌ Vendor with ID {vendor_id} not found")
            )

    def handle_all_vendors(self):
        """Check all vendors"""
        results = BalanceReconciliationService.reconcile_all_balances()
        
        self.display_summary(results['summary'])
        
        # Show problematic vendors
        inconsistent_vendors = [
            v for v in results['vendor_results'] 
            if not v['is_consistent']
        ]
        
        if inconsistent_vendors:
            self.stdout.write("\n🔴 Vendors with inconsistencies:")
            self.stdout.write("-" * 60)
            
            for vendor in inconsistent_vendors:
                self.display_vendor_result(vendor, brief=True)
                
                # Show warning - but no automatic correction
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  Vendor {vendor['vendor_id']} requires manual review"
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n🎉 All vendors are consistent!")
            )

    def display_summary(self, summary):
        """Display general summary"""
        self.stdout.write(f"\n📊 General Summary:")
        self.stdout.write(f"   Total vendors: {summary['total_vendors']}")

        if summary['consistent_vendors'] > 0:
            self.stdout.write(
                self.style.SUCCESS(f"   ✅ Consistent: {summary['consistent_vendors']} ({summary['consistency_percentage']:.1f}%)")
            )
        
        if summary['inconsistent_vendors'] > 0:
            self.stdout.write(
                self.style.ERROR(f"   ❌ Inconsistent: {summary['inconsistent_vendors']}")
            )
            self.stdout.write(f"   💰 Total difference: {summary['total_difference']:,} Toman")

        stats = summary['system_stats']
        self.stdout.write(f"\n📈 System Statistics:")
        self.stdout.write(f"   Total transactions: {stats['total_transactions']:,}")
        self.stdout.write(f"   Total credits: {stats['total_credits']:,} Toman")
        self.stdout.write(f"   Total sales: {stats['total_sales']:,} Toman")
        self.stdout.write(f"   Net balance: {stats['net_system_balance']:,} Toman")

    def display_vendor_result(self, result, brief=False):
        """Display result for a vendor"""
        vendor_id = result['vendor_id']
        vendor_name = result['vendor_name']
        is_consistent = result['is_consistent']
        
        status_icon = "✅" if is_consistent else "❌"
        status_color = self.style.SUCCESS if is_consistent else self.style.ERROR
        
        if brief:
            self.stdout.write(
                f"     {status_icon} Vendor {vendor_id} ({vendor_name}): "
                f"Difference {result['difference']:,} Toman"
            )
        else:
            self.stdout.write(status_color(f"\n{status_icon} Vendor {vendor_id} ({vendor_name})"))
            self.stdout.write(f"   Current balance: {result['stored_balance']:,} Toman")
            self.stdout.write(f"   Calculated balance: {result['calculated_balance']:,} Toman")

            if not is_consistent:
                self.stdout.write(
                    self.style.WARNING(f"   ⚠️  Difference: {result['difference']:,} Toman")
                )
            
            summary = result['transaction_summary']
            self.stdout.write(f"   📈 Credits: {summary['total_credits']:,} Toman ({summary['credit_transactions_count']} transactions)")
            self.stdout.write(f"   📉 Sales: {summary['total_sales']:,} Toman ({summary['sale_transactions_count']} transactions)")

    def generate_report_file(self, vendor_id=None):
        """Generate report file"""
        try:
            report = BalanceReconciliationService.generate_reconciliation_report(vendor_id)
            filename = f"balance_reconciliation_report_{int(time.time())}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report)
            
            self.stdout.write(
                self.style.SUCCESS(f"📄 Report saved: {filename}")
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error saving report: {str(e)}")
            )
