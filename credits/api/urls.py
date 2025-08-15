from django.urls import path
from credits.api.views import CreditRequestViewSet

credit_list = CreditRequestViewSet.as_view({
    'get': 'list',
    'post': 'create'
})

urlpatterns = [
    path('', credit_list, name='credits-list-create'),
]