from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from datetime import date
from decimal import Decimal, InvalidOperation

from clients.models import Client
from equipment.models import Equipment, EquipmentType
from rentals.models import Rental, RentalItem
from payments.models import Payment


ROLE_DASHBOARDS = {
    "admin": "dashboard",
    "manager": "dashboard",
    "cashier": "dashboard",
}

ACTIVE_RENTAL_STATUSES = ("open", "booked", "rented")


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

    # Статистика, чтобы на дашборде отображались данные, созданные в admin.
    active_rentals_qs = Rental.objects.filter(status__in=("open", "booked", "rented"))
    active_rentals_count = active_rentals_qs.count()
    active_clients_count = (
        Client.objects.filter(rentals__in=active_rentals_qs).distinct().count()
    )

    equipment_units_total = (
        Equipment.objects.aggregate(total=Sum("quantity"))["total"] or 0
    )

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    total_income_month = (
        Payment.objects.filter(status="paid", created_at__gte=month_start, created_at__lt=next_month)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )

    context = {
        "user": user,
        "role": user.role,
        "is_admin": user.role == "admin",
        "is_manager": user.role in ("admin", "manager"),
        "is_cashier": user.role in ("admin", "manager", "cashier"),

        "active_clients_count": active_clients_count,
        "active_rentals_count": active_rentals_count,
        "equipment_units_total": equipment_units_total,
        "total_income_month": total_income_month,
    }
    return render(request, "dashboard.html", context)


@login_required(login_url="login")
def clients_page(request):
    """Страница клиентов (только admin/manager)."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    error = None
    if request.method == "POST":
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
def equipment_page(request):
    """Страница снаряжения (только admin/manager)."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    error = None
    equipment_types = EquipmentType.objects.order_by("name")

    if request.method == "POST":
        equipment_type_name = request.POST.get("equipment_type_name", "").strip()
        equipment_type_id = request.POST.get("equipment_type_id", "").strip()
        equipment_name = request.POST.get("equipment_name", "").strip()
        size = request.POST.get("size", "").strip() or None
        status = request.POST.get("status", "available").strip()

        price_per_day_raw = request.POST.get("price_per_day", "").strip()
        quantity_raw = request.POST.get("quantity", "").strip()

        if not equipment_name or not price_per_day_raw or not quantity_raw:
            error = "Заполните обязательные поля: название, цена/день и количество."
        else:
            try:
                price_per_day = Decimal(price_per_day_raw)
                quantity = int(quantity_raw)
            except (ValueError, InvalidOperation):
                error = "Некорректный формат цены или количества."
            else:
                if equipment_type_name:
                    et = EquipmentType.objects.create(name=equipment_type_name)
                else:
                    if not equipment_type_id:
                        error = "Выберите тип снаряжения."
                        et = None
                    else:
                        et = get_object_or_404(EquipmentType, pk=equipment_type_id)

                if et is not None:
                    Equipment.objects.create(
                        name=equipment_name,
                        type=et,
                        size=size,
                        status=status,
                        price_per_day=price_per_day,
                        quantity=quantity,
                    )
                    return redirect("equipment")

    equipments = Equipment.objects.select_related("type").order_by(
        "type__name", "name"
    )

    total_units = Equipment.objects.aggregate(total=Sum("quantity"))["total"] or 0
    total_rented_units = (
        Equipment.objects.aggregate(total=Sum("quantity_rented"))["total"] or 0
    )
    available_units = total_units - total_rented_units

    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "equipments": equipments,
        "total_units": total_units,
        "available_units": available_units,
        "total_rented_units": total_rented_units,
        "equipment_types": equipment_types,
        "error": error,
    }
    return render(request, "equipment.html", context)


@login_required(login_url="login")
def rentals_page(request):
    """Страница аренды (только admin/manager)."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    error = None
    clients = Client.objects.order_by("-created_at")
    equipments = Equipment.objects.order_by("name")

    if request.method == "POST":
        client_id = request.POST.get("client_id", "").strip()
        equipment_ids = request.POST.getlist("equipment_ids")
        days_raw = request.POST.get("days", "1").strip()
        start_date_raw = request.POST.get("start_date", "").strip()
        status = request.POST.get("status", "draft").strip()

        if not client_id or not equipment_ids:
            error = "Выберите клиента и снаряжение."
        else:
            try:
                days = int(days_raw)
                if days < 1:
                    raise ValueError("days")
            except ValueError:
                error = "Дней должно быть целое число >= 1."
            else:
                client = get_object_or_404(Client, pk=client_id)
                equipment_qs = Equipment.objects.filter(pk__in=equipment_ids)
                if not equipment_qs.exists():
                    error = "Выбранные товары не найдены."

                if start_date_raw:
                    try:
                        start_d = date.fromisoformat(start_date_raw)
                    except ValueError:
                        error = "Некорректная дата начала."
                else:
                    start_d = date.today()

                if error is None:
                    end_d = start_d + timedelta(days=days - 1)
                    rental = Rental.objects.create(
                        client=client,
                        status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                        start_date=start_d,
                        end_date=end_d,
                    )
                    for equipment in equipment_qs:
                        RentalItem.objects.create(
                            rental=rental,
                            equipment=equipment,
                            price_per_day=equipment.price_per_day,
                            days=days,
                        )
                    # На всякий случай фиксируем итог после создания всех позиций.
                    rental.total_price = rental.calculate_total_price()
                    rental.save(update_fields=["total_price"])
                    return redirect("rentals")

    rentals = Rental.objects.select_related("client").order_by("-created_at")

    total_rentals_count = Rental.objects.count()
    active_rentals_count = rentals.filter(status__in=ACTIVE_RENTAL_STATUSES).count()
    draft_rentals_count = rentals.filter(status="draft").count()

    active_rentals_total_price = (
        rentals.filter(status__in=ACTIVE_RENTAL_STATUSES).aggregate(total=Sum("total_price"))[
            "total"
        ]
        or 0
    )

    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "rentals": rentals,
        "clients": clients,
        "equipments": equipments,
        "error": error,
        "total_rentals_count": total_rentals_count,
        "active_rentals_count": active_rentals_count,
        "draft_rentals_count": draft_rentals_count,
        "active_rentals_total_price": active_rentals_total_price,
    }
    return render(request, "rentals.html", context)


@login_required(login_url="login")
def payments_page(request):
    """Страница платежей (доступна admin/manager/cashier)."""
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    paid_in_month_qs = Payment.objects.filter(
        status="paid", created_at__gte=month_start, created_at__lt=next_month
    )

    total_income_month = (
        paid_in_month_qs.aggregate(total=Sum("amount"))["total"] or 0
    )
    paid_in_month_count = paid_in_month_qs.count()

    payment_methods_breakdown = (
        paid_in_month_qs.values("payment_method")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    payment_methods_count = payment_methods_breakdown.count()

    payments = (
        Payment.objects.select_related("rental__client")
        .order_by("-created_at")
    )

    error = None
    if request.method == "POST":
        if request.user.role not in ("admin", "manager", "cashier"):
            return redirect("dashboard")

        rental_id = request.POST.get("rental_id", "").strip()
        payment_method = request.POST.get("payment_method", "").strip()
        amount_raw = request.POST.get("amount", "").strip()

        if not rental_id or not payment_method or not amount_raw:
            error = "Заполните обязательные поля: договор, метод оплаты и сумма."
        else:
            try:
                amount = Decimal(amount_raw)
            except (ValueError, InvalidOperation):
                error = "Некорректная сумма."

        if error is None:
            rental = get_object_or_404(Rental, pk=rental_id)
            if rental.client_id is None:
                error = "У выбранного договора не указан клиент."
            else:
                # Пересчитываем итог по позициям договора перед созданием платежа,
                # чтобы на странице договора/платежей всегда отображалась корректная сумма.
                rental.total_price = rental.calculate_total_price()
                rental.save(update_fields=["total_price"])
                Payment.objects.create(
                    rental=rental,
                    amount=amount,
                    payment_method=payment_method,
                    status="paid",  # Платеж считается успешным автоматически
                )
                return redirect("payments")

    rentals_for_select = (
        Rental.objects.filter(client__isnull=False)
        .select_related("client")
        .order_by("-created_at")
    )

    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "payments": payments,
        "total_income_month": total_income_month,
        "paid_in_month_count": paid_in_month_count,
        "payment_methods_breakdown": payment_methods_breakdown,
        "payment_methods_count": payment_methods_count,
        "error": error,
        "rentals_for_select": rentals_for_select,
    }
    return render(request, "payments.html", context)