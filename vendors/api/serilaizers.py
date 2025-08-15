from rest_framework import serializers
from vendors.models import Vendor
from django.contrib.auth.models import User

class VendorSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    email = serializers.EmailField(write_only=True)

    class Meta:
        model = Vendor
        fields = ['id', 'name', 'balance', 'username', 'password', 'email', 'is_active']
        read_only_fields = ['id', 'balance']

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')
        email = validated_data.pop('email')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        vendor = Vendor.objects.create(
            user=user,
            **validated_data
        )

        return vendor
