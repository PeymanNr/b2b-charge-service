from django.urls import path

from charges.api.views import ChargeViewSet

charge_list = ChargeViewSet.as_view({
    'get': 'list',
    'post': 'create'
})

urlpatterns = [
    path('', charge_list, name='charge-list-create'),
]