import logging
from rest_framework import viewsets, status
from rest_framework.response import Response
from credits.api.serializers import CreditRequestSerializer
from credits.models import CreditRequest
from vendors.models import Vendor
from credits.services import CreditService
from utils.security_managers import SecurityAuditLogger


logger = logging.getLogger(__name__)
audit_logger = SecurityAuditLogger()


class CreditRequestViewSet(viewsets.ViewSet):
    """
    Secure Credit Request ViewSet using service layer
    Nested under Vendor: /api/vendors/{vendor_id}/credits/
    """
    def list(self, request):
        """Get all credits requests for the authenticated user's vendor"""
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

        queryset = CreditRequest.objects.filter(vendor=vendor).order_by('-created_at')
        serializer = CreditRequestSerializer(queryset, many=True)

        return Response({
            'success': True,
            'data': serializer.data
        })

    def create(self, request):
        """Create a new credits request for the authenticated user's vendor"""
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

        # Create a mutable copy of request data and add vendor
        request_data = request.data.copy()
        request_data['vendor'] = vendor.id

        serializer = CreditRequestSerializer(data=request_data)
        if not serializer.is_valid():
            return Response({'success': False, 'message': serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)

        # Use secure service layer to create credits request
        success, message, credit_request = CreditService.create_credit_request(
            vendor=vendor,
            amount=serializer.validated_data['amount']
        )

        if success:
            response_serializer = CreditRequestSerializer(credit_request)
            return Response({
                'success': True,
                'message': message,
                'data': response_serializer.data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                'success': False,
                'message': message
            }, status=status.HTTP_400_BAD_REQUEST)
