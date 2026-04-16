from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("clients/", views.clients_page, name="clients"),
    path("equipment/", views.equipment_page, name="equipment"),
    path("rentals/", views.rentals_page, name="rentals"),
    path("payments/", views.payments_page, name="payments"),
]