from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from datetime import timedelta
from datetime import date
from decimal import Decimal, InvalidOperation
from django.contrib.auth import get_user_model

from clients.models import Client
from equipment.models import Equipment, EquipmentType
from rentals.models import (Rental, RentalItem, Discount, PriceModifier, Contract)
from rentals.services import generate_contract_text
from payments.models import Payment


ROLE_DASHBOARDS = {
    "admin": "dashboard",
    "manager": "dashboard",
    "cashier": "dashboard",
}

ACTIVE_RENTAL_STATUSES = ("open", "booked", "rented")
User = get_user_model()


def _close_expired_rentals():
    today = timezone.localdate()
    Rental.objects.filter(
        status__in=ACTIVE_RENTAL_STATUSES,
        end_date__lt=today,
    ).update(status="completed")


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


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        full_name = request.POST.get("full_name", "").strip()
        role = request.POST.get("role", "cashier").strip()

        if not username or not password or not full_name:
            error = "Заполните обязательные поля."
        elif User.objects.filter(username=username).exists():
            error = "Пользователь с таким логином уже существует."
        else:
            first_name, *rest = full_name.split(" ", 1)
            last_name = rest[0] if rest else ""
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role if role in dict(User.ROLE_CHOICES) else "cashier",
            )
            login(request, user)
            return redirect("dashboard")

    return render(request, "register.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
def dashboard(request):
    """Главный дашборд. Контекст содержит роль пользователя для ветвления в шаблоне."""
    user = request.user
    _close_expired_rentals()

    if request.method == "POST" and request.user.role == "admin":
        action = request.POST.get("action", "").strip()
        if action == "create_discount":
            name = request.POST.get("name", "").strip()
            percent = request.POST.get("percent", "").strip()
            min_days = request.POST.get("min_days", "").strip()
            if name and percent and min_days:
                Discount.objects.create(name=name, percent=int(percent), min_days=int(min_days))
                messages.success(request, "Скидка добавлена.")
                return redirect("dashboard")
        if action == "delete_discount":
            discount_id = request.POST.get("discount_id", "").strip()
            if discount_id:
                discount = get_object_or_404(Discount, pk=discount_id)
                discount.delete()
                messages.success(request, "Скидка удалена.")
            return redirect("dashboard")
        if action == "edit_discount":
            discount_id = request.POST.get("discount_id", "").strip()
            name = request.POST.get("name", "").strip()
            percent = request.POST.get("percent", "").strip()
            min_days = request.POST.get("min_days", "").strip()
            if discount_id and name and percent and min_days:
                discount = get_object_or_404(Discount, pk=discount_id)
                discount.name = name
                discount.percent = int(percent)
                discount.min_days = int(min_days)
                discount.save(update_fields=["name", "percent", "min_days"])
                messages.success(request, "Скидка обновлена.")
            return redirect("dashboard")
        if action == "save_modifiers":
            weekend = request.POST.get("weekday_multiplier", "").strip()
            holiday = request.POST.get("holiday_multiplier", "").strip()
            if weekend and holiday:
                modifier = PriceModifier.objects.first()
                if modifier is None:
                    modifier = PriceModifier.objects.create(
                        weekday_multiplier=float(weekend),
                        holiday_multiplier=float(holiday),
                    )
                else:
                    modifier.weekday_multiplier = float(weekend)
                    modifier.holiday_multiplier = float(holiday)
                    modifier.save()
                messages.success(request, "Модификаторы сохранены.")
                return redirect("dashboard")

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
        "discounts": Discount.objects.order_by("min_days"),
        "price_modifier": PriceModifier.objects.first(),
    }
    return render(request, "dashboard.html", context)


@login_required(login_url="login")
def clients_page(request):
    """Страница клиентов (только admin/manager)."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")
    _close_expired_rentals()

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
def equipment_page(request):
    """Страница снаряжения (только admin/manager)."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")
    _close_expired_rentals()

    error = None
    equipment_types = EquipmentType.objects.order_by("name")

    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "delete" and request.user.role == "admin":
            equipment = get_object_or_404(Equipment, pk=request.POST.get("equipment_id"))
            equipment.delete()
            messages.success(request, "Снаряжение удалено.")
            return redirect("equipment")
        if action == "status":
            equipment = get_object_or_404(Equipment, pk=request.POST.get("equipment_id"))
            new_status = request.POST.get("new_status", "").strip()
            if new_status in dict(Equipment.STATUS_CHOICES):
                equipment.status = new_status
                equipment.save(update_fields=["status"])
                messages.success(request, "Статус снаряжения обновлён.")
            return redirect("equipment")
        if action == "update":
            equipment = get_object_or_404(Equipment, pk=request.POST.get("equipment_id"))
            equipment.name = request.POST.get("equipment_name", "").strip()
            equipment.size = request.POST.get("size", "").strip()
            equipment.price_per_day = Decimal(request.POST.get("price_per_day", "0").strip() or "0")
            equipment.quantity = int(request.POST.get("quantity", "1").strip() or 1)
            equipment.save()
            messages.success(request, "Снаряжение обновлено.")
            return redirect("equipment")
        if action == "create":
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
    _close_expired_rentals()

    error = None
    clients = Client.objects.order_by("-created_at")
    equipments = Equipment.objects.order_by("name")

    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "status" and request.user.role == "admin":
            rental = get_object_or_404(Rental, pk=request.POST.get("rental_id"))
            new_status = request.POST.get("new_status", "").strip()
            if new_status in dict(Rental.STATUS_CHOICES):
                rental.status = new_status
                rental.save(update_fields=["status"])
                messages.success(request, "Статус аренды обновлён.")
            return redirect("rentals")
        if action == "delete" and request.user.role == "admin":
            rental = get_object_or_404(Rental, pk=request.POST.get("rental_id"))
            rental.delete()
            messages.success(request, "Аренда удалена.")
            return redirect("rentals")
        if action == "create":
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
                        rental.total_price = rental.calculate_total_price()
                        rental.save(update_fields=["total_price"])
                        messages.success(request, "Аренда добавлена.")
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
    _close_expired_rentals()

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
    }
    return render(request, "payments.html", context)


@login_required(login_url="login")
def payment_create_page(request):
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    error = None
    if request.method == "POST":
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
            else:
                rental = get_object_or_404(Rental, pk=rental_id)
                rental.total_price = rental.calculate_total_price()
                rental.save(update_fields=["total_price"])
                Payment.objects.create(
                    rental=rental,
                    amount=amount,
                    payment_method=payment_method,
                    status="paid",
                )
                messages.success(request, "Платёж добавлен.")
                return redirect("payments")
    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "rentals_for_select": Rental.objects.filter(client__isnull=False).select_related("client").order_by("-created_at"),
        "error": error,
    }
    return render(request, "forms/payment_form.html", context)


@login_required(login_url="login")
def rental_edit_page(request, rental_id):
    if request.user.role != "admin":
        return redirect("rentals")
    rental = get_object_or_404(Rental, pk=rental_id)
    error = None
    if request.method == "POST":
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw = request.POST.get("end_date", "").strip()
        try:
            start_d = date.fromisoformat(start_date_raw) if start_date_raw else None
            end_d = date.fromisoformat(end_date_raw) if end_date_raw else None
            if start_d and end_d and end_d < start_d:
                raise ValueError()
        except ValueError:
            error = "Проверьте даты договора."
        else:
            rental.start_date = start_d
            rental.end_date = end_d
            rental.save()
            messages.success(request, "Данные аренды обновлены.")
            return redirect("rentals")
    context = {
        "user": request.user,
        "role": request.user.role,
        "is_admin": True,
        "is_manager": True,
        "is_cashier": True,
        "rental": rental,
        "error": error,
    }
    return render(request, "rental_edit.html", context)


@login_required(login_url="login")
def client_create_page(request):
    if request.user.role not in ("admin", "manager"):
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
                Client.objects.create(full_name=full_name, phone=phone, email=email, document_id=document_id)
                messages.success(request, "Клиент добавлен.")
            return redirect("clients")
    return render(request, "forms/client_form.html", {"user": request.user, "role": request.user.role, "is_admin": request.user.role == "admin", "is_manager": request.user.role in ("admin", "manager"), "is_cashier": request.user.role in ("admin", "manager", "cashier"), "error": error, "client": client})


@login_required(login_url="login")
def rental_create_page(request):
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
            except ValueError:
                error = "Дней должно быть целое число >= 1."
            else:
                client = get_object_or_404(Client, pk=client_id)
                equipment_qs = Equipment.objects.filter(pk__in=equipment_ids)
                start_d = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
                end_d = start_d + timedelta(days=max(days, 1) - 1)
                rental = Rental.objects.create(client=client, status=status if status in dict(Rental.STATUS_CHOICES) else "draft", start_date=start_d, end_date=end_d)
                for equipment in equipment_qs:
                    RentalItem.objects.create(rental=rental, equipment=equipment, price_per_day=equipment.price_per_day, days=max(days, 1))
                rental.total_price = rental.calculate_total_price()
                rental.save(update_fields=["total_price"])
                messages.success(request, "Аренда добавлена.")
                return redirect("rentals")
    return render(request, "forms/rental_form.html", {"user": request.user, "role": request.user.role, "is_admin": request.user.role == "admin", "is_manager": request.user.role in ("admin", "manager"), "is_cashier": request.user.role in ("admin", "manager", "cashier"), "clients": clients, "equipments": equipments, "error": error})


@login_required(login_url="login")
def equipment_create_page(request):
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")
    error = None
    edit_id = request.GET.get("edit")
    equipment = get_object_or_404(Equipment, pk=edit_id) if edit_id else None
    equipment_types = EquipmentType.objects.order_by("name")
    if request.method == "POST":
        equipment_type_name = request.POST.get("equipment_type_name", "").strip()
        equipment_type_id = request.POST.get("equipment_type_id", "").strip()
        equipment_name = request.POST.get("equipment_name", "").strip()
        size = request.POST.get("size", "").strip() or None
        status = request.POST.get("status", "available").strip()
        price_per_day_raw = request.POST.get("price_per_day", "").strip()
        quantity_raw = request.POST.get("quantity", "").strip()
        try:
            price_per_day = Decimal(price_per_day_raw)
            quantity = int(quantity_raw)
        except (ValueError, InvalidOperation):
            error = "Некорректный формат цены или количества."
        else:
            if equipment_type_name:
                et = EquipmentType.objects.create(name=equipment_type_name)
            else:
                et = get_object_or_404(EquipmentType, pk=equipment_type_id) if equipment_type_id else None
            if et is None:
                error = "Выберите тип снаряжения."
            else:
                if equipment:
                    equipment.name = equipment_name
                    equipment.type = et
                    equipment.size = size
                    equipment.status = status
                    equipment.price_per_day = price_per_day
                    equipment.quantity = quantity
                    equipment.save()
                    messages.success(request, "Снаряжение обновлено.")
                else:
                    Equipment.objects.create(name=equipment_name, type=et, size=size, status=status, price_per_day=price_per_day, quantity=quantity)
                    messages.success(request, "Снаряжение добавлено.")
                return redirect("equipment")
    return render(request, "forms/equipment_form.html", {"user": request.user, "role": request.user.role, "is_admin": request.user.role == "admin", "is_manager": request.user.role in ("admin", "manager"), "is_cashier": request.user.role in ("admin", "manager", "cashier"), "equipment_types": equipment_types, "error": error, "equipment": equipment})


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


@login_required(login_url='login')
def contract_create_web(request, rental_id):
    """
    Создаёт договор для аренды (если ещё нет) и редиректит на страницу договора.
    URL: /contracts/create/<rental_id>/
    """
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')

    rental = get_object_or_404(Rental.objects.select_related('client'), pk=rental_id)

    if not rental.client:
        messages.error(request, 'У аренды нет клиента — нельзя создать договор.')
        return redirect('rentals')

    # Если договор уже существует — сразу перейти к нему
    try:
        contract = rental.contract
    except Exception:
        contract = Contract.objects.create(
            client=rental.client,
            rental=rental,
            text=generate_contract_text(rental.client, rental),
            status='sent',
        )

    return redirect('contract_detail', contract_id=contract.id)


@login_required(login_url='login')
def contract_detail_page(request, contract_id):
    """
    Страница договора с подписанием через ЭЦП (карт-ридер) или SMS.
    URL: /contracts/<contract_id>/
    """
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')

    contract = get_object_or_404(
        Contract.objects.select_related('client', 'rental'),
        pk=contract_id,
    )
    signatures = contract.signatures.select_related('operator').order_by('-signed_at')

    context = {
        'user':       request.user,
        'role':       request.user.role,
        'is_admin':   request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': request.user.role in ('admin', 'manager', 'cashier'),
        'contract':   contract,
        'rental':     contract.rental,
        'client':     contract.client,
        'signatures': signatures,
    }
    return render(request, 'contract_detail.html', context)    