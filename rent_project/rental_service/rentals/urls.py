from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    RentalViewSet, PaymentViewSet, DashboardView,
    CreateContractView, ContractSmsSendView, ContractSmsVerifyView, StartRentalView,
    SignCardView,
    settings_view, create_draft, delete_rental, change_status, ContractSmsSendView, ContractSmsVerifyView
)
from equipment.views import ClientViewSet, EquipmentViewSet, EquipmentTypeViewSet

router = DefaultRouter()
router.register(r'rentals', RentalViewSet)
router.register(r'clients', ClientViewSet)
router.register(r'equipment', EquipmentViewSet)
router.register(r'equipment-types', EquipmentTypeViewSet)
router.register(r'payments', PaymentViewSet)

urlpatterns = [
    path('settings/',                              settings_view,            name='settings'),
    path('rentals/create-draft/',                  create_draft,             name='create_draft'),
    path('rentals/<int:pk>/delete/',               delete_rental,            name='delete_rental'),
    path('rentals/<int:pk>/status/',               change_status,            name='change_status'),
    path('api/dashboard/',                         DashboardView.as_view(),  name='api_dashboard'),

    path('contract/<int:contract_id>/sms/send/', ContractSmsSendView.as_view()),
    path('contract/<int:contract_id>/sms/verify/', ContractSmsVerifyView.as_view()),

    # Договоры
    path('contract/create/<int:rental_id>/',       CreateContractView.as_view(),  name='contract_create_api'),

    # ★ Подписание через карт-ридер (NCALayer ЭЦП)
    path('api/sign/card/<int:contract_id>/',       SignCardView.as_view(),        name='sign_card'),

    path('rental/start/<int:rental_id>/',          StartRentalView.as_view(),     name='rental_start'),
] + router.urls
