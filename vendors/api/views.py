from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from vendors.api.serilaizers import VendorSerializer
from vendors.models import Vendor
import logging


logger = logging.getLogger(__name__)


class VendorViewSet(viewsets.ModelViewSet):
    serializer_class = VendorSerializer
    http_method_names = ['get', 'post']

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Vendor.objects.all()
        return Vendor.objects.filter(user=user)

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return [IsAuthenticated()]
