from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ContractSmsSendView,
    ContractSmsVerifyView,
    CreateContractView,
    RentalViewSet,
    SignCardView,
    StartRentalView,
)

router = DefaultRouter()
router.register(r'rentals', RentalViewSet)

urlpatterns = [
    path('contract/create/<int:rental_id>/',       CreateContractView.as_view(),    name='contract_create_api'),
    path('contract/<int:contract_id>/sms/send/',   ContractSmsSendView.as_view(),   name='contract_sms_send'),
    path('contract/<int:contract_id>/sms/verify/', ContractSmsVerifyView.as_view(), name='contract_sms_verify'),
    path('sign/card/<int:contract_id>/',           SignCardView.as_view(),          name='sign_card'),
    path('rental/start/<int:rental_id>/',          StartRentalView.as_view(),       name='rental_start'),
] + router.urls
