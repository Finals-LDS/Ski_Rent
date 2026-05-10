from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from users.views import CustomTokenObtainPairView


urlpatterns = [
    path("admin/", admin.site.urls),

    # ── JWT auth (кастомный — токен включает роль) ────────────────────
    path("api/token/",         CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(),          name="token_refresh"),

    # ── REST API ──────────────────────────────────────────────────────
    path("api/users/",     include("users.urls")),
    path("api/clients/",   include("clients.urls")),
    path("api/equipment/", include("equipment.urls")),
    path("api/rentals/",   include("rentals.urls")),
    path("api/payments/",  include("payments.urls")),

    # ── Web (HTML страницы) ───────────────────────────────────────────
    # Доменно-специфичные страницы каждого приложения
    path("", include("clients.urls_web")),
    path("", include("equipment.urls_web")),
    path("", include("rentals.urls_web")),
    path("", include("payments.urls_web")),
    path("", include("users.urls_web")),

    # Кросс-приложенческие (auth, dashboard, analytics, AI, settings)
    path("", include("web.urls")),
]
