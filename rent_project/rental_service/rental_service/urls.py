from django.contrib import admin
from django.urls import path, include
from users.views import CustomTokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # JWT auth (кастомный — включает роль)
    path("api/token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Users API
    path("api/users/", include("users.urls")),

    # Domain APIs
    path("api/clients/", include("clients.urls")),
    path("api/equipment/", include("equipment.urls")),
    path("api/rentals/", include("rentals.urls")),
    path("api/payments/", include("payments.urls")),

    # Web (HTML-страницы)
    path("", include("web.urls")),
]