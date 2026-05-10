from rest_framework.routers import DefaultRouter

from .views import PaymentViewSet

router = DefaultRouter()
router.register(r'payments', PaymentViewSet)

urlpatterns = router.urls
