from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import *
from equipment.views import ClientViewSet, EquipmentViewSet, EquipmentTypeViewSet

router = DefaultRouter()
router.register(r'api/rentals', RentalViewSet)
router.register(r'api/rentals', ClientViewSet)
router.register(r'api/rentals', EquipmentViewSet)
router.register(r'api/rentals', EquipmentTypeViewSet)
router.register(r'api/rentals', PaymentViewSet)

urlpatterns = [
    path('settings/', settings_view, name='settings'),
    path('rentals/create-draft/', create_draft, name='create_draft'),
    path('rentals/<int:pk>/delete/', delete_rental, name='delete_rental'),
    path('rentals/<int:pk>/status/', change_status, name='change_status'),
    path('api/dashboard/', DashboardView.as_view(), name='api_dashboard'),
    path('contract/create/<int:rental_id>/', CreateContractView.as_view()),
    path('contract/accept/<int:contract_id>/', AcceptContractView.as_view()),
    path('rental/start/<int:rental_id>/', StartRentalView.as_view()),
] + router.urls