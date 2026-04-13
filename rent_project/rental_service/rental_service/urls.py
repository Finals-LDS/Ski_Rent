from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),

    # JWT
    path("api/token/", TokenObtainPairView.as_view()),
    path("api/token/refresh/", TokenRefreshView.as_view()),

    # apps
    path("api/clients/", include("clients.urls")),
    path("api/equipment/", include("equipment.urls")),
    path("api/rentals/", include("rentals.urls")),
    path("api/payments/", include("payments.urls")),
]