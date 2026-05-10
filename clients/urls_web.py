from django.urls import path

from . import views

urlpatterns = [
    path('clients/',         views.clients_page,              name='clients'),
    path('clients/new/',     views.client_create_page,        name='client_create'),
    path('birthday/send/',   views.send_birthday_emails_view, name='send_birthday_emails'),
]
