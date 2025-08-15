from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.routers import DefaultRouter

from charges.api.views import ChargeViewSet
from vendors.api.views import VendorViewSet

# Swagger documentation setup
schema_view = get_schema_view(
    openapi.Info(
        title="B2B Charge Service API",
        default_version='v1',
        description="API for B2B phone charging service",
        terms_of_service="https://www.example.com/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

router = DefaultRouter()
router.register(r'api/vendors', VendorViewSet, basename='vendor')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include(router.urls)),
    path("api/vendor/credits/", include("credits.api.urls")),
    path("api/vendor/charges/", include("charges.api.urls")),
    path("api/vendor/transactions/", include("transactions.api.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]
