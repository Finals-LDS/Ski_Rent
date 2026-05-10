from django.urls import path

from . import views

urlpatterns = [
    path('payments/',                         views.payments_page,        name='payments'),
    path('payments/new/',                     views.payment_create_page,  name='payment_create'),
    path('payments/<int:payment_id>/refund/', views.payment_refund_page,  name='payment_refund'),
]
