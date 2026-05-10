from django.urls import path

from . import views

urlpatterns = [
    path('rentals/',                        views.rentals_page,          name='rentals'),
    path('rentals/new/',                    views.rental_create_page,    name='rental_create'),
    path('rentals/<int:rental_id>/edit/',   views.rental_edit_page,      name='rental_edit'),

    path('contracts/create/<int:rental_id>/', views.contract_create_web,    name='contract_create_web'),
    path('contracts/<int:contract_id>/',      views.contract_detail_page,   name='contract_detail'),
    path('contracts/<int:contract_id>/pdf/',  views.contract_pdf_download,  name='contract_pdf_download'),
]
