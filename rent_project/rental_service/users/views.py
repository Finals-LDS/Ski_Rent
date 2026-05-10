from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .permissions import IsAdmin
from .serializers import CustomTokenObtainPairSerializer, UserSerializer


User = get_user_model()


# ─────────────────────────────────────────
#  REST API Views
# ─────────────────────────────────────────
class CustomTokenObtainPairView(TokenObtainPairView):
    """POST /api/token/ — получить JWT с ролью пользователя."""
    serializer_class = CustomTokenObtainPairSerializer


class UserListView(APIView):
    """GET /api/users/ — список пользователей (только admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        users = User.objects.all().order_by("username")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            password = request.data.get("password")
            user = serializer.save()
            if password:
                user.set_password(password)
                user.save()
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDetailView(APIView):
    """GET/PATCH/DELETE /api/users/<id>/ — управление пользователем (только admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def _get_user(self, pk):
        try:
            return User.objects.get(pk=pk)
        except User.DoesNotExist:
            return None

    def get(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            if "password" in request.data:
                user.set_password(request.data["password"])
                user.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────
#  Web pages (moved from web/views.py)
# ─────────────────────────────────────────
@login_required(login_url="login")
def users_page(request):
    if request.user.role != "admin":
        return redirect("dashboard")

    error = None
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "create":
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "").strip()
            full_name = request.POST.get("full_name", "").strip()
            role = request.POST.get("role", "cashier").strip()
            if not username or not password or not full_name:
                error = "Заполните обязательные поля для пользователя."
            elif User.objects.filter(username=username).exists():
                error = "Логин уже используется."
            else:
                first_name, *rest = full_name.split(" ", 1)
                last_name = rest[0] if rest else ""
                User.objects.create_user(
                    username=username,
                    password=password,
                    role=role if role in dict(User.ROLE_CHOICES) else "cashier",
                    first_name=first_name,
                    last_name=last_name,
                )
                messages.success(request, "Пользователь добавлен.")
                return redirect("users")
        elif action == "update":
            target = get_object_or_404(User, pk=request.POST.get("user_id"))
            target.first_name = request.POST.get("first_name", "").strip()
            target.last_name = request.POST.get("last_name", "").strip()
            target.email = request.POST.get("email", "").strip()
            new_role = request.POST.get("role", target.role)
            if new_role in dict(User.ROLE_CHOICES):
                target.role = new_role
            target.save()
            messages.success(request, "Пользователь обновлён.")
            return redirect("users")
        elif action == "delete":
            target = get_object_or_404(User, pk=request.POST.get("user_id"))
            if target.pk == request.user.pk:
                error = "Нельзя удалить текущего пользователя."
            else:
                target.delete()
                messages.success(request, "Пользователь удалён.")
                return redirect("users")
        elif action == "profile":
            request.user.first_name = request.POST.get("profile_first_name", "").strip()
            request.user.last_name = request.POST.get("profile_last_name", "").strip()
            request.user.email = request.POST.get("profile_email", "").strip()
            request.user.save()
            messages.success(request, "Профиль обновлён.")
            return redirect("users")

    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": True,
        "is_manager": True,
        "is_cashier": True,
        "users": User.objects.order_by("username"),
        "error": error,
    }
    return render(request, "users.html", context)
