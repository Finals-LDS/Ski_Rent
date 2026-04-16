from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required


ROLE_DASHBOARDS = {
    "admin": "dashboard",
    "manager": "dashboard",
    "cashier": "dashboard",
}


def login_view(request):
    """Страница входа. После успеха — редирект на дашборд по роли."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            error = "Введите имя пользователя и пароль."
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get("next") or ROLE_DASHBOARDS.get(user.role, "dashboard")
                return redirect(next_url)
            else:
                error = "Неверный логин или пароль."

    return render(request, "login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
def dashboard(request):
    """Главный дашборд. Контекст содержит роль пользователя для ветвления в шаблоне."""
    user = request.user
    context = {
        "user": user,
        "role": user.role,
        "is_admin": user.role == "admin",
        "is_manager": user.role in ("admin", "manager"),
        "is_cashier": user.role in ("admin", "manager", "cashier"),
    }
    return render(request, "dashboard.html", context)