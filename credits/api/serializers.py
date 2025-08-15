from rest_framework import serializers
from credits.models import CreditRequest
from decimal import Decimal

class CreditRequestSerializer(serializers.ModelSerializer):
    """Serializer for credits request operations with enhanced validation"""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)

    class Meta:
        model = CreditRequest
        fields = [
            'id', 'vendor', 'vendor_name', 'amount', 'status',
            'status_display', 'rejection_reason', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'rejection_reason', 'created_at', 'updated_at']

    def validate_amount(self, value):
        """Validate credits amount with comprehensive checks"""
        if value <= Decimal('0'):
            raise serializers.ValidationError("مبلغ باید بیشتر از صفر باشد")
        if value > Decimal('50000000'):  # 50 million limit
            raise serializers.ValidationError("مبلغ از حداکثر حد مجاز بیشتر است")
        if value < Decimal('1000'):  # Minimum 1000 limit
            raise serializers.ValidationError("حداقل مبلغ درخواست ۱۰۰۰ تومان است")
        return value


class CreditRequestApprovalSerializer(serializers.Serializer):
    """Serializer for admin credits request approval/rejection"""

    action = serializers.ChoiceField(
        choices=[('approve', 'تایید'), ('reject', 'رد')],
        help_text="عمل مورد نظر"
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="دلیل رد درخواست (در صورت رد)"
    )

    def validate(self, data):
        """Validate approval/rejection data"""
        if data['action'] == 'reject' and not data.get('reason', '').strip():
            raise serializers.ValidationError({
                'reason': 'دلیل رد درخواست الزامی است'
            })
        return data
