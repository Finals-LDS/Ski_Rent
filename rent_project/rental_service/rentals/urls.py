from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    RentalViewSet, PaymentViewSet, DashboardView,
    CreateContractView, AcceptContractView, StartRentalView,
    SignCardView,
    settings_view, create_draft, delete_rental, change_status,
)
from equipment.views import ClientViewSet, EquipmentViewSet, EquipmentTypeViewSet

router = DefaultRouter()
router.register(r'api/rentals', RentalViewSet)
router.register(r'api/rentals', ClientViewSet)
router.register(r'api/rentals', EquipmentViewSet)
router.register(r'api/rentals', EquipmentTypeViewSet)
router.register(r'api/rentals', PaymentViewSet)

urlpatterns = [
    path('settings/',                              settings_view,            name='settings'),
    path('rentals/create-draft/',                  create_draft,             name='create_draft'),
    path('rentals/<int:pk>/delete/',               delete_rental,            name='delete_rental'),
    path('rentals/<int:pk>/status/',               change_status,            name='change_status'),
    path('api/dashboard/',                         DashboardView.as_view(),  name='api_dashboard'),

    # Договоры
    path('contract/create/<int:rental_id>/',       CreateContractView.as_view(),  name='contract_create_api'),
    path('contract/accept/<int:contract_id>/',     AcceptContractView.as_view(),  name='contract_accept'),

    # ★ Подписание через карт-ридер (NCALayer ЭЦП)
    path('api/sign/card/<int:contract_id>/',       SignCardView.as_view(),        name='sign_card'),

    path('rental/start/<int:rental_id>/',          StartRentalView.as_view(),     name='rental_start'),
] + router.urls
