from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import CustomTokenObtainPairSerializer, UserSerializer
from .permissions import IsAdmin


class CustomTokenObtainPairView(TokenObtainPairView):
    """POST /api/token/ — получить JWT с ролью пользователя."""
    serializer_class = CustomTokenObtainPairSerializer


class MeView(APIView):
    """GET /api/users/me/ — профиль текущего пользователя."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class UserListView(APIView):
    """GET /api/users/ — список пользователей (только admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        users = User.objects.all().order_by("username")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
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
        from django.contrib.auth import get_user_model
        User = get_user_model()
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