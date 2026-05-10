from rest_framework.routers import DefaultRouter

from .views import EquipmentViewSet, EquipmentTypeViewSet

router = DefaultRouter()
router.register(r'equipment', EquipmentViewSet)
router.register(r'equipment-types', EquipmentTypeViewSet)

urlpatterns = router.urls
