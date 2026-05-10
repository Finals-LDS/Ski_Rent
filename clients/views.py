from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from rest_framework.viewsets import ModelViewSet

from .models import Client
from .serializers import ClientSerializer


ACTIVE_RENTAL_STATUSES = ("open", "booked", "rented")


# ─────────────────────────────────────────
#  REST API ViewSet
# ─────────────────────────────────────────
class ClientViewSet(ModelViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer


# ─────────────────────────────────────────
#  Web pages (moved from web/views.py)
# ─────────────────────────────────────────
@login_required(login_url="login")
def clients_page(request):
    """Страница клиентов (admin/manager/cashier)."""
    from rentals.utils import close_expired_rentals
    from rentals.models import Rental

    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    close_expired_rentals()

    error = None
    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "delete" and request.user.role == "admin":
            client = get_object_or_404(Client, pk=request.POST.get("client_id"))
            client.delete()
            messages.success(request, "Клиент удалён.")
            return redirect("clients")
        if action == "create":
            full_name = request.POST.get("full_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            email = request.POST.get("email", "").strip() or None
            document_id = request.POST.get("document_id", "").strip() or None

            if not full_name or not phone:
                error = "Заполните обязательные поля: ФИО и телефон."
            else:
                Client.objects.create(
                    full_name=full_name,
                    phone=phone,
                    email=email,
                    document_id=document_id,
                )
                messages.success(request, "Клиент добавлен.")
                return redirect("clients")
        if action == "update":
            client = get_object_or_404(Client, pk=request.POST.get("client_id"))
            client.full_name = request.POST.get("full_name", "").strip()
            client.phone = request.POST.get("phone", "").strip()
            client.email = request.POST.get("email", "").strip()
            client.document_id = request.POST.get("document_id", "").strip()
            client.save()
            messages.success(request, "Клиент обновлён.")
            return redirect("clients")

    active_clients_count = (
        Client.objects.filter(rentals__status__in=ACTIVE_RENTAL_STATUSES)
        .distinct()
        .count()
    )
    active_rentals_count = Rental.objects.filter(
        status__in=ACTIVE_RENTAL_STATUSES
    ).count()

    clients = (
        Client.objects.annotate(
            active_rentals_count=Count(
                "rentals",
                filter=Q(rentals__status__in=ACTIVE_RENTAL_STATUSES),
            )
        )
        .order_by("-created_at")
    )

    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "total_clients_count": clients.count(),
        "active_clients_count": active_clients_count,
        "active_rentals_count": active_rentals_count,
        "clients": clients,
        "error": error,
    }
    return render(request, "clients.html", context)


@login_required(login_url="login")
def client_create_page(request):
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    error = None
    edit_id = request.GET.get("edit")
    client = get_object_or_404(Client, pk=edit_id) if edit_id else None
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip() or None
        document_id = request.POST.get("document_id", "").strip() or None
        if not full_name or not phone:
            error = "Заполните обязательные поля: ФИО и телефон."
        else:
            if client:
                client.full_name = full_name
                client.phone = phone
                client.email = email
                client.document_id = document_id
                client.save()
                messages.success(request, "Клиент обновлён.")
            else:
                Client.objects.create(
                    full_name=full_name, phone=phone,
                    email=email, document_id=document_id,
                )
                messages.success(request, "Клиент добавлен.")
            return redirect("clients")
    return render(request, "forms/client_form.html", {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "error": error,
        "client": client,
    })


@login_required(login_url='login')
@require_POST
def send_birthday_emails_view(request):
    """Отправляет поздравительные письма именинникам (вызывается из UI)."""
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    try:
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('send_birthday_emails', '--discount=15', stdout=out)
        messages.success(request, f'Поздравления отправлены! {out.getvalue()}')
    except Exception as exc:
        messages.error(request, f'Ошибка при отправке: {exc}')
    return redirect('analytics')
