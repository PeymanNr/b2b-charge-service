from rest_framework import serializers
from phonenumber_field.serializerfields import PhoneNumberField
from decimal import Decimal
from charges.models import Charge


class ChargeSerializer(serializers.ModelSerializer):
    """Serializer for Charge model"""
    
    phone_number = PhoneNumberField(read_only=True)
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)

    class Meta:
        model = Charge
        fields = [
            'id', 'vendor', 'vendor_name', 'phone_number',
            'amount', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ChargePhoneSerializer(serializers.Serializer):
    """Serializer for phone charging with comprehensive validation"""

    phone_number = PhoneNumberField(required=True, help_text="Mobile phone number")
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('100'),
        max_value=Decimal('1000000'),
        help_text="Charge amount (minimum 100, maximum 1,000,000 Toman)"
    )
    idempotency_key = serializers.CharField(
        required=False,
        max_length=255,
        help_text="Unique key to prevent duplicate transactions"
    )

    def validate_amount(self, value):
        """Enhanced amount validation"""
        if value <= Decimal('0'):
            raise serializers.ValidationError("Amount must be positive")

        # Check if amount is in valid increments (multiples of 100)
        if value % Decimal('100') != 0:
            raise serializers.ValidationError("Amount must be multiple of 100 Toman")

        return value
