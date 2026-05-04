from django.urls import path
from . import views

urlpatterns = [
    path('',                                    views.login_view,              name='login'),
    path('register/',                           views.register_view,           name='register'),
    path('logout/',                             views.logout_view,             name='logout'),
    path('dashboard/',                          views.dashboard,               name='dashboard'),

    path('clients/',                            views.clients_page,            name='clients'),
    path('clients/new/',                        views.client_create_page,      name='client_create'),

    path('equipment/',                          views.equipment_page,          name='equipment'),
    path('warehouse/',                          views.warehouse_view,          name='warehouse'),
    path('equipment/new/',                      views.equipment_create_page,   name='equipment_create'),

    path('rentals/',                            views.rentals_page,            name='rentals'),
    path('rentals/new/',                        views.rental_create_page,      name='rental_create'),
    path('rentals/<int:rental_id>/edit/',       views.rental_edit_page,        name='rental_edit'),

    path('payments/',                           views.payments_page,           name='payments'),
    path('payments/new/',                       views.payment_create_page,     name='payment_create'),
    path('payments/<int:payment_id>/refund/',   views.payment_refund_page,     name='payment_refund'),

    path('users/',                              views.users_page,              name='users'),

    path('contracts/create/<int:rental_id>/',   views.contract_create_web,     name='contract_create_web'),
    path('contracts/<int:contract_id>/',        views.contract_detail_page,    name='contract_detail'),
    path('contracts/<int:contract_id>/pdf/',    views.contract_pdf_download,   name='contract_pdf_download'),

    path('profile/',                            views.profile_view,            name='profile'),

    # Analytics
    path('analytics/',                          views.analytics_view,          name='analytics'),
    path('analytics/export/',                   views.analytics_export,        name='analytics_export'),

    # AI Assistant (Решид)
    path('ai-chat/',                            views.ai_chat_view,            name='ai_chat'),

    # App settings
    path('settings/',                           views.app_settings_view,       name='app_settings'),

    # Birthday emails
    path('birthday/send/',                      views.send_birthday_emails_view, name='send_birthday_emails'),
]
