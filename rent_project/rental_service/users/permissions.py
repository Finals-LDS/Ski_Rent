from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Только администраторы."""
    message = "Доступ разрешён только администраторам."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsManager(BasePermission):
    """Менеджеры и администраторы."""
    message = "Доступ разрешён менеджерам и администраторам."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "manager")
        )


class IsCashier(BasePermission):
    """Кассиры, менеджеры и администраторы."""
    message = "Доступ разрешён кассирам, менеджерам и администраторам."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "manager", "cashier")
        )


class IsAdminOrReadOnly(BasePermission):
    """Чтение для всех авторизованных, запись — только для admin."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role == "admin"