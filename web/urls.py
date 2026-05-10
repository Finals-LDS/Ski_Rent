from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path('',          views.login_view,    name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/',   views.logout_view,   name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Analytics
    path('analytics/',        views.analytics_view,   name='analytics'),
    path('analytics/export/', views.analytics_export, name='analytics_export'),

    # AI Assistant (Решид) — Groq
    path('ai-chat/', views.ai_chat_view, name='ai_chat'),

    # App settings
    path('settings/', views.app_settings_view, name='app_settings'),
]
