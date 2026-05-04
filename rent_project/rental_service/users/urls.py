from django.urls import path
from .views import MeView, UserListView, UserDetailView

urlpatterns = [
    path("me/", MeView.as_view(), name="user-me"),
    path("", UserListView.as_view(), name="user-list"),
    path("<int:pk>/", UserDetailView.as_view(), name="user-detail"),
]