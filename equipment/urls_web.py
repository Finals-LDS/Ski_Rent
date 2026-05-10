from django.urls import path

from . import views

urlpatterns = [
    path('equipment/',     views.equipment_page,        name='equipment'),
    path('equipment/new/', views.equipment_create_page, name='equipment_create'),
    path('warehouse/',     views.warehouse_view,        name='warehouse'),
]
