from rest_framework import serializers
from transactions.models import Transaction
from utils.enums import TransactionType, TransactionStatus


class TransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display', 'amount',
            'phone_number', 'balance_before', 'balance_after',
            'status', 'status_display', 'description', 'is_successful',
            'created_at'
        ]

    def get_transaction_type_display(self, obj):
        """Get human readable transaction type"""
        if obj.transaction_type == TransactionType.CREDIT.value:
            return 'افزایش اعتبار'
        elif obj.transaction_type == TransactionType.SALE.value:
            return 'فروش شارژ'
        return 'نامشخص'

    def get_status_display(self, obj):
        """Get human readable status"""
        if obj.status == TransactionStatus.PENDING.value:
            return 'در انتظار'
        elif obj.status == TransactionStatus.APPROVED.value:
            return 'تایید شده'
        elif obj.status == TransactionStatus.REJECTED.value:
            return 'رد شده'
        return 'نامشخص'

    def to_representation(self, instance):
        """Convert all data to simple types"""
        data = super().to_representation(instance)

        # Convert all Decimal fields to string
        data['amount'] = str(instance.amount)
        data['balance_before'] = str(instance.balance_before)
        data['balance_after'] = str(instance.balance_after)

        return data


class VendorTransactionSummarySerializer(serializers.Serializer):
    """Serializer for vendor transaction summary with balance reconciliation"""
    vendor_id = serializers.IntegerField()
    vendor_name = serializers.CharField()
    current_balance = serializers.DecimalField(max_digits=15, decimal_places=2)

    # Transaction counts
    total_transactions = serializers.IntegerField()
    credit_transactions = serializers.IntegerField()
    sale_transactions = serializers.IntegerField()
    pending_transactions = serializers.IntegerField()

    # Financial summary
    total_credits = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_sales = serializers.DecimalField(max_digits=15, decimal_places=2)
    calculated_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_difference = serializers.DecimalField(max_digits=15, decimal_places=2)
    is_balance_consistent = serializers.BooleanField()

    # Transaction list
    transactions = TransactionSerializer(many=True)
