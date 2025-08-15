import logging
import uuid
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.response import Response
from charges.api.serializers import ChargeSerializer, ChargePhoneSerializer
from charges.models import Charge
from charges.services import ChargeManagement
from vendors.models import Vendor
from credits.services import CreditManagement
from utils.security_managers import SecurityAuditLogger

logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class ChargeViewSet(viewsets.ViewSet):
    """
    Ultra-secure Phone Charging ViewSet using service layer
    URL: /api/vendors/charges/ - vendor determined from JWT token
    """

    def list(self, request):
        """Get all charges for the authenticated user's vendor"""
        try:
            vendor = Vendor.objects.get(user=request.user)
        except Vendor.DoesNotExist:
            audit_logger.log_security_event(
                'USER_HAS_NO_VENDOR',
                None,
                {'user': request.user.username},
                'WARNING'
            )
            return Response({
                'success': False,
                'message': 'شما هیچ فروشنده‌ای ندارید'
            }, status=status.HTTP_404_NOT_FOUND)

        # Get charges using the manager
        queryset = Charge.objects.get_vendor_charges(vendor.id)
        
        # Add pagination support
        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        start = (page - 1) * page_size
        end = start + page_size
        
        charges = queryset[start:end]
        total_count = queryset.count()
        
        serializer = ChargeSerializer(charges, many=True)

        return Response({
            'success': True,
            'data': serializer.data,
            'pagination': {
                'current_page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': (total_count + page_size - 1) // page_size
            }
        })

    def create(self, request):
        """Create a new phone charge for the authenticated user's vendor"""
        # Get the vendor from the authenticated user
        try:
            vendor = Vendor.objects.get(user=request.user)
        except Vendor.DoesNotExist:
            audit_logger.log_security_event(
                'USER_HAS_NO_VENDOR',
                None,
                {'user': request.user.username},
                'WARNING'
            )
            return Response({
                'success': False,
                'message': 'شما هیچ فروشنده‌ای ندارید'
            }, status=status.HTTP_404_NOT_FOUND)


        serializer = ChargePhoneSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'message': serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)

        phone_number = serializer.validated_data['phone_number']
        amount = serializer.validated_data['amount']
        idempotency_key = serializer.validated_data.get('idempotency_key', str(uuid.uuid4()))

        # Additional security check for concurrent requests
        lock_key = f"charge_lock_{vendor.id}_{idempotency_key}"
        if cache.get(lock_key):
            return Response({
                'success': False,
                'message': 'درخواست در حال پردازش است'
            }, status=status.HTTP_409_CONFLICT)

        cache.set(lock_key, True, timeout=30)

        try:
            success, transaction_obj, message = ChargeManagement.charge_phone(
                vendor=vendor,
                phone_number=phone_number,
                amount=amount,
                idempotency_key=idempotency_key
            )

            if not success:
                # Determine appropriate HTTP status based on error type
                if 'موجودی ناکافی' in message:
                    status_code = status.HTTP_402_PAYMENT_REQUIRED
                elif 'محدودیت' in message:
                    status_code = status.HTTP_429_TOO_MANY_REQUESTS
                else:
                    status_code = status.HTTP_400_BAD_REQUEST

                return Response({
                    'success': False,
                    'message': message
                }, status=status_code)

            return Response({
                'success': True,
                'message': message,
                'data': {
                    'transaction_id': str(transaction_obj.id),
                    'phone_number': str(phone_number),
                    'amount': str(amount),
                    'remaining_balance': str(vendor.balance)
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Unexpected error in charge endpoint: {str(e)}", exc_info=True)
            audit_logger.log_security_event(
                'CHARGE_ENDPOINT_ERROR',
                vendor.id,
                {'error': str(e), 'phone': str(phone_number), 'amount': str(amount)},
                'ERROR'
            )
            return Response({
                'success': False,
                'message': 'خطای سیستم رخ داده است'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            cache.delete(lock_key)

