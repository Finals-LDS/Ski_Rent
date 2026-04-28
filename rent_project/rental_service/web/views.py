import csv
import io
import json
from django.db.models import Sum, Count, Q
from django.http import HttpResponse
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
    send_birthday_emails()

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

        "recent_refunds": Payment.objects.filter(status="ferund")
            .select_related("rental__client")
            .order_by("-created_at")[:10],
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
            birth_date_raw = request.POST.get("birth_date", "").strip() or None
            birth_date = None
            if birth_date_raw:
                try:
                    birth_date = date.fromisoformat(birth_date_raw)
                except ValueError:
                    pass

            if not full_name or not phone:
                error = "Заполните обязательные поля: ФИО и телефон."
            else:
                Client.objects.create(
                    full_name=full_name, phone=phone,
                    email=email, document_id=document_id, birth_date=birth_date,
                )
                messages.success(request, "Клиент добавлен.")
                return redirect("clients")
        if action == "update":
            client = get_object_or_404(Client, pk=request.POST.get("client_id"))
            client.full_name = request.POST.get("full_name", "").strip()
            client.phone = request.POST.get("phone", "").strip()
            client.email = request.POST.get("email", "").strip()
            client.document_id = request.POST.get("document_id", "").strip()
            birth_date_raw = request.POST.get("birth_date", "").strip() or None
            if birth_date_raw:
                try:
                    client.birth_date = date.fromisoformat(birth_date_raw)
                except ValueError:
                    pass
            else:
                client.birth_date = None
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
            days_raw = request.POST.get("days", "1").strip()
            start_date_raw = request.POST.get("start_date", "").strip()
            status = request.POST.get("status", "draft").strip()

            item_rows = request.POST.getlist("item_rows")
            items_data = []
            for row_id in item_rows:
                eq_id = request.POST.get(f"eq_id_{row_id}", "").strip()
                eq_size = request.POST.get(f"eq_size_{row_id}", "").strip()
                eq_qty_raw = request.POST.get(f"eq_qty_{row_id}", "1").strip()
                if eq_id:
                    try:
                        eq_qty = max(1, int(eq_qty_raw))
                    except ValueError:
                        eq_qty = 1
                    items_data.append({"eq_id": eq_id, "size": eq_size, "qty": eq_qty})
            
            if not client_id or not items_data:
                error = "Выберите клиента и добавьте хотя бы одну позицию снаряжения."
            else:
                client = get_object_or_404(Client, pk=client_id)

                if start_date_raw:
                    try:
                        start_d = date.fromisoformat(start_date_raw)
                    except ValueError:
                        error = "Некорректная дата начала."
                else: start_d = date.today()

                if error is None:
                    eq_ids = [it["eq_id"] for it in items_data]
                    equipment_map = {
                        str(e.pk): e
                        for e in Equipment.objects.filter(pk__in=eq_ids)
                    }
                    if not equipment_map:
                        error = "Выбранные позиции снаряжения не найдены."

                if error is None:
                    end_d = dtart_d + timedelta(days=days - 1)
                    rental = Rental.objects.create(
                        client=client,
                        status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                        start_date=start_d,
                        end_date=end_d,
                    )
                    for it in items_data:
                        equipment = equipment_map.get(it["eq_id"])
                        if  equipment:
                            RentalItem.objects.create(
                                rental=rental,
                                equipment=equipment,
                                price_per_day=equipment.price_per_day,
                                days=days,
                                size=it["size"],
                                quantity=it["qty"],
                            )
                    rental.total_price = rental.calculate_total_price()
                    rental.save(update_fields=["total_price"])
                    messages.success(request, "Аренда добавлена.")
                    return redirect("rentals")

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
    """
    GET  → показывает форму
    POST → получает данные, создаёт Payment в базе
    """
    # Только три роли имеют доступ
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")

    # Словарь разрешённых методов:
    # ключ   — что придёт из HTML (скрытое поле methodInput)
    # значение — что запишется в базу данных
    # Это серверная валидация — защита от подделки запроса
    ALLOWED_METHODS = {
        "kaspi": "Kaspi Bank",
        "halyk": "Halyk Bank",
        "cash":  "Наличные",
    }

    error = None

    if request.method == "POST":
        rental_id      = request.POST.get("rental_id", "").strip()
        payment_method = request.POST.get("payment_method", "").strip()
        amount_raw     = request.POST.get("amount", "").strip()

        # Валидация 1: все поля заполнены?
        if not rental_id or not payment_method or not amount_raw:
            error = "Заполните обязательные поля: договор, метод оплаты и сумма."

        # Валидация 2: метод из разрешённого списка?
        elif payment_method not in ALLOWED_METHODS:
            error = "Выберите корректный метод оплаты."

        else:
            try:
                # Decimal точнее float для денег (нет ошибок округления)
                amount = Decimal(amount_raw)
            except (ValueError, InvalidOperation):
                error = "Некорректная сумма."
            else:
                # get_object_or_404 — вернёт 404 если договор не найден
                rental = get_object_or_404(Rental, pk=rental_id)
                rental.total_price = rental.calculate_total_price()
                rental.save(update_fields=["total_price"])

                Payment.objects.create(
                    rental=rental,
                    amount=amount,
                    payment_method=ALLOWED_METHODS[payment_method],  # "Kaspi Bank" / "Halyk Bank" / "Наличные"
                    status="paid",
                )
                messages.success(request, "Платёж добавлен.")
                return redirect("payments")

    # Передаём в шаблон через context — доступны как {{ rentals_for_select }} и т.д.
    context = {
        "user":       request.user,
        "role":       request.user.role,
        "is_admin":   request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        # select_related("client") — загружает клиента одним SQL-запросом (оптимизация)
        "rentals_for_select": Rental.objects.filter(
            client__isnull=False
        ).select_related("client").order_by("-created_at"),
        "error": error,
    }
    return render(request, "forms/payment_form.html", context)

@login_required(login_url="login")
def payment_refund_page(request, payment_id):
    """
    Страница возврата средств по конкретному платежу.
    payment_id — ID платежа из URL (/payments/42/refund/)
    
    GET  → показывает форму возврата с данными платежа
    POST → создаёт новый Payment со статусом "refund"
    """
    # Только менеджер и админ могут делать возвраты
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    # Получаем оригинальный платёж — если не найден, вернёт 404
    original_payment = get_object_or_404(Payment, pk=payment_id)

    # Нельзя делать возврат на возврат
    if original_payment.status == "refund":
        messages.error(request, "Нельзя сделать возврат на уже возвращённый платёж.")
        return redirect("payments")

    # Считаем уже возвращённую сумму по этому платежу
    # Может быть несколько частичных возвратов — суммируем их
    already_refunded = Payment.objects.filter(
        rental=original_payment.rental,
        status="refund",
        # related_payment — смотри поле ниже, пока просто фильтруем по аренде
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Максимум к возврату = оплачено - уже возвращено
    max_refund = original_payment.amount + already_refunded  # already_refunded отрицательное
    
    error = None

    if request.method == "POST":
        refund_amount_raw    = request.POST.get("refund_amount", "").strip()
        refund_method        = request.POST.get("refund_method", "").strip()
        refund_reason        = request.POST.get("refund_reason", "").strip()

        if not refund_amount_raw or not refund_method:
            error = "Укажите сумму и способ возврата."
        else:
            try:
                refund_amount = Decimal(refund_amount_raw)
            except (ValueError, InvalidOperation):
                error = "Некорректная сумма."
            else:
                if refund_amount <= 0:
                    error = "Сумма возврата должна быть больше нуля."
                elif refund_amount > max_refund:
                    error = f"Сумма возврата не может превышать {max_refund} ₸."
                else:
                    # Создаём платёж-возврат
                    # amount отрицательный — чтобы при подсчёте баланса он вычитался
                    Payment.objects.create(
                        rental=original_payment.rental,
                        amount=-refund_amount,          # ОТРИЦАТЕЛЬНАЯ СУММА
                        payment_method=refund_method,
                        status="refund",
                        change_amount=Decimal("0"),
                    )
                    messages.success(
                        request,
                        f"Возврат {refund_amount} ₸ выполнен успешно."
                    )
                    return redirect("payments")

    context = {
        "user":             request.user,
        "role":             request.user.role,
        "is_admin":         request.user.role == "admin",
        "is_manager":       request.user.role in ("admin", "manager"),
        "original_payment": original_payment,
        "max_refund":       max_refund,
        "error":            error,
    }
    return render(request, "forms/refund_form.html", context)

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
        birth_date_raw = request.POST.get("birth_date", "").strip() or None
        birth_date = None
        if birth_date_raw:
            try:
                birth_date = date.fromisoformat(birth_date_raw)
            except ValueError:
                pass
        if not full_name or not phone:
            error = "Заполните обязательные поля: ФИО и телефон."
        else:
            if client:
                client.full_name = full_name
                client.phone = phone
                client.email = email
                client.document_id = document_id
                client.birth_date = birth_date
                client.save()
                messages.success(request, "Клиент обновлён.")
            else:
                Client.objects.create(
                    full_name=full_name, phone=phone, email=email,
                    document_id=document_id, birth_date=birth_date,
                )
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
        client_id      = request.POST.get("client_id", "").strip()
        days_raw       = request.POST.get("days", "1").strip()
        start_date_raw = request.POST.get("start_date", "").strip()
        status         = request.POST.get("status", "draft").strip()

        # Собираем строки снаряжения из динамических полей eq_id_1, eq_id_2 ...
        item_rows = request.POST.getlist("item_rows")  # маркеры строк из JS

        items = []
        for n in item_rows:
            eq_id  = request.POST.get(f"eq_id_{n}", "").strip()
            qty    = request.POST.get(f"eq_qty_{n}", "1").strip()
            size   = request.POST.get(f"eq_size_{n}", "").strip()
            if eq_id:
                items.append({"eq_id": eq_id, "qty": int(qty) if qty.isdigit() else 1, "size": size})

        if not client_id:
            error = "Выберите клиента."
        elif not items:
            error = "Добавьте хотя бы одно снаряжение."
        else:
            try:
                days = int(days_raw)
                if days < 1:
                    raise ValueError
            except ValueError:
                error = "Дней должно быть целое число >= 1."
            else:
                client  = get_object_or_404(Client, pk=client_id)
                start_d = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
                end_d   = start_d + timedelta(days=max(days, 1) - 1)

                rental = Rental.objects.create(
                    client=client,
                    status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                    start_date=start_d,
                    end_date=end_d,
                )

                for item in items:
                    equipment = get_object_or_404(Equipment, pk=item["eq_id"])
                    RentalItem.objects.create(
                        rental=rental,
                        equipment=equipment,
                        price_per_day=equipment.price_per_day,
                        days=max(days, 1),
                        quantity=item["qty"],
                        size=item["size"] or None,
                    )

                rental.total_price = rental.calculate_total_price()
                rental.save(update_fields=["total_price"])
                messages.success(request, "Аренда добавлена.")
                return redirect("rentals")


                client = get_object_or_404(Client, pk=client_id)
                equipment_qs = Equipment.objects.filter(pk__in=equipment_ids)
                start_d = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
                end_d = start_d + timedelta(days=max(days, 1) - 1)

                discount_id = request.POST.get("discount_id", "").strip()

                rental = Rental.objects.create(
                    client=client,
                    status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                    start_date=start_d,
                    end_date=end_d,
                    discount=Discount.objects.filter(pk=discount_id).first() if discount_id else None,
                )

    return render(request, "forms/rental_form.html", {
        "user":       request.user,
        "role":       request.user.role,
        "is_admin":   request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "clients":    clients,
        "equipments": equipments,
        "error":      error,
        "discounts": Discount.objects.order_by("min_days"),
    })

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


# ─────────────────────────────────────────────────────────────
# АНАЛИТИКА
# ─────────────────────────────────────────────────────────────

@login_required(login_url='login')
def analytics_page(request):
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')

    export = request.GET.get('export', '')

    # CSV: журнал платежей
    if export == 'payments_csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="payments.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Клиент', 'Договор', 'Сумма', 'Метод', 'Статус', 'Дата'])
        for p in Payment.objects.select_related('rental__client').order_by('-created_at'):
            client_name = p.rental.client.full_name if p.rental.client else '—'
            writer.writerow([
                p.id, client_name, p.rental.contract_number,
                p.amount, p.payment_method, p.get_status_display(),
                p.created_at.strftime('%d.%m.%Y %H:%M'),
            ])
        return response

    # CSV: аренды
    if export == 'rentals_csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="rentals.csv"'
        writer = csv.writer(response)
        writer.writerow(['Договор', 'Клиент', 'Статус', 'Начало', 'Конец', 'Сумма', 'Создан'])
        for r in Rental.objects.select_related('client').order_by('-created_at'):
            writer.writerow([
                r.contract_number,
                r.client.full_name if r.client else '—',
                r.get_status_display(),
                r.start_date or '—', r.end_date or '—',
                r.total_price,
                r.created_at.strftime('%d.%m.%Y'),
            ])
        return response

    # CSV: снаряжение
    if export == 'equipment_csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="equipment.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Название', 'Тип', 'Размер', 'Статус', 'Цена/день', 'Кол-во'])
        from equipment.models import Equipment as Eq
        for eq in Eq.objects.select_related('type').order_by('type__name', 'name'):
            writer.writerow([
                eq.id, eq.name, eq.type.name if eq.type else '—',
                eq.size or '—', eq.get_status_display(), eq.price_per_day, eq.quantity,
            ])
        return response

    # Excel: все отчёты в одном файле
    if export == 'excel':
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            messages.error(request, 'Установите openpyxl для экспорта Excel.')
            return redirect('analytics')

        wb = Workbook()

        # Лист 1: Журнал платежей
        ws1 = wb.active
        ws1.title = 'Платежи'
        headers1 = ['ID', 'Клиент', 'Договор', 'Сумма', 'Метод', 'Статус', 'Дата']
        ws1.append(headers1)
        for cell in ws1[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='1C2130')
        for p in Payment.objects.select_related('rental__client').order_by('-created_at'):
            client_name = p.rental.client.full_name if p.rental.client else '—'
            ws1.append([
                p.id, client_name, p.rental.contract_number,
                float(p.amount), p.payment_method, p.get_status_display(),
                p.created_at.strftime('%d.%m.%Y %H:%M'),
            ])

        # Лист 2: Аренды
        ws2 = wb.create_sheet('Аренды')
        headers2 = ['Договор', 'Клиент', 'Статус', 'Начало', 'Конец', 'Сумма', 'Создан']
        ws2.append(headers2)
        for cell in ws2[1]:
            cell.font = Font(bold=True)
        for r in Rental.objects.select_related('client').order_by('-created_at'):
            ws2.append([
                r.contract_number,
                r.client.full_name if r.client else '—',
                r.get_status_display(),
                str(r.start_date or '—'), str(r.end_date or '—'),
                float(r.total_price),
                r.created_at.strftime('%d.%m.%Y'),
            ])

        # Лист 3: Снаряжение
        ws3 = wb.create_sheet('Снаряжение')
        headers3 = ['ID', 'Название', 'Тип', 'Размер', 'Статус', 'Цена/день', 'Кол-во']
        ws3.append(headers3)
        for cell in ws3[1]:
            cell.font = Font(bold=True)
        from equipment.models import Equipment as Eq
        for eq in Eq.objects.select_related('type').order_by('type__name', 'name'):
            ws3.append([
                eq.id, eq.name, eq.type.name if eq.type else '—',
                eq.size or '—', eq.get_status_display(),
                float(eq.price_per_day), eq.quantity,
            ])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="skirent_report.xlsx"'
        return response

    # ── Данные для дашбордов ────────────────────────────────
    today = timezone.localdate()

    # Выручка по месяцам (последние 12 месяцев)
    monthly_revenue = []
    monthly_labels = []
    for i in range(11, -1, -1):
        # вычисляем первый день месяца
        if today.month - i <= 0:
            m = today.month - i + 12
            y = today.year - 1
        else:
            m = today.month - i
            y = today.year
        month_start = today.replace(year=y, month=m, day=1)
        if m == 12:
            month_end = month_start.replace(year=y + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=m + 1, day=1)
        revenue = (
            Payment.objects.filter(
                status='paid',
                created_at__date__gte=month_start,
                created_at__date__lt=month_end,
            ).aggregate(t=Sum('amount'))['t'] or 0
        )
        monthly_revenue.append(float(revenue))
        monthly_labels.append(f'{m:02d}.{y}')

    # Аренды по статусам
    rental_statuses = {}
    for code, label in Rental.STATUS_CHOICES:
        rental_statuses[label] = Rental.objects.filter(status=code).count()

    # Методы оплаты (текущий месяц)
    month_start_dt = today.replace(day=1)
    payment_methods_qs = (
        Payment.objects.filter(status='paid', created_at__date__gte=month_start_dt)
        .values('payment_method')
        .annotate(total=Sum('amount'), cnt=Count('id'))
    )
    payment_methods = {p['payment_method']: {'total': float(p['total']), 'count': p['cnt']}
                       for p in payment_methods_qs}

    # Топ-5 клиентов
    top_clients = list(
        Rental.objects.values('client__full_name')
        .annotate(total_spent=Sum('total_price'))
        .order_by('-total_spent')[:5]
    )

    # Общая статистика
    total_revenue = Payment.objects.filter(status='paid').aggregate(t=Sum('amount'))['t'] or 0
    total_refunds = abs(
        Payment.objects.filter(status='refund').aggregate(t=Sum('amount'))['t'] or 0
    )
    total_rentals = Rental.objects.count()
    completed_rentals = Rental.objects.filter(status='completed').count()
    total_clients = Client.objects.count()

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin': request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': request.user.role in ('admin', 'manager', 'cashier'),

        'total_revenue': total_revenue,
        'total_refunds': total_refunds,
        'total_rentals': total_rentals,
        'completed_rentals': completed_rentals,
        'total_clients': total_clients,

        'monthly_labels_json': json.dumps(monthly_labels),
        'monthly_revenue_json': json.dumps(monthly_revenue),
        'rental_statuses_json': json.dumps(rental_statuses),
        'payment_methods_json': json.dumps(payment_methods),
        'top_clients_json': json.dumps([
            {'name': c['client__full_name'] or '—', 'total': float(c['total_spent'] or 0)}
            for c in top_clients
        ]),
    }
    return render(request, 'analytics.html', context)


# ─────────────────────────────────────────────────────────────
# ИИ ПОМОЩНИК
# ─────────────────────────────────────────────────────────────

@login_required(login_url='login')
def ai_chat_view(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        body = json.loads(request.body)
        user_message = body.get('message', '').strip()
    except Exception:
        return HttpResponse('{"error":"bad request"}', content_type='application/json', status=400)

    if not user_message:
        return HttpResponse('{"error":"empty message"}', content_type='application/json', status=400)

    try:
        import anthropic
        from django.conf import settings as django_settings

        api_key = getattr(django_settings, 'ANTHROPIC_API_KEY', '')
        if not api_key:
            import os
            api_key = os.environ.get('ANTHROPIC_API_KEY', '')

        client_ai = anthropic.Anthropic(api_key=api_key)

        system_prompt = (
            "Ты — виртуальный помощник для обучения персонала компании Ski Rent. "
            "Компания предоставляет услуги проката горнолыжного снаряжения: лыжи, ботинки, палки, шлемы, защиту. "
            "Ты помогаешь кассирам и менеджерам:\n"
            "- Оформлять аренду снаряжения (создать аренду → добавить позиции → создать договор → получить подпись → начать аренду)\n"
            "- Работать с клиентами: регистрация, поиск, обновление данных\n"
            "- Принимать платежи: наличные, Kaspi Bank, Halyk Bank\n"
            "- Делать возвраты и управлять скидками\n"
            "- Понимать статусы аренды: черновик → открыт → забронирован → арендован → завершён / отменён\n"
            "- Работать с отчётами и аналитикой\n"
            "Отвечай кратко, по делу, на русском языке. При необходимости давай пошаговые инструкции."
        )

        message = client_ai.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1024,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_message}],
        )
        reply = message.content[0].text
    except Exception as e:
        reply = f'Ошибка ИИ помощника: {e}'

    return HttpResponse(
        json.dumps({'reply': reply}, ensure_ascii=False),
        content_type='application/json',
    )


# ─────────────────────────────────────────────────────────────
# ПОЗДРАВЛЕНИЯ С ДНЁМ РОЖДЕНИЯ
# ─────────────────────────────────────────────────────────────

def send_birthday_emails():
    """
    Отправляет поздравления клиентам, у которых сегодня день рождения.
    Вызывается один раз в день при загрузке дашборда.
    """
    from django.core.mail import send_mail
    from django.conf import settings as django_settings

    today = timezone.localdate()
    year = today.year

    clients_today = Client.objects.filter(
        birth_date__month=today.month,
        birth_date__day=today.day,
        email__isnull=False,
    ).exclude(email='').exclude(birthday_email_sent_year=year)

    for client in clients_today:
        if not client.email:
            continue
        subject = f'🎉 С Днём Рождения, {client.full_name.split()[0]}! — Ski Rent'
        body = (
            f'Уважаемый(ая) {client.full_name},\n\n'
            f'Команда Ski Rent поздравляет Вас с Днём Рождения! 🎿\n\n'
            f'В честь праздника мы дарим Вам специальную скидку 10% на любую аренду снаряжения '
            f'в течение 7 дней. Просто назовите свой номер телефона при оформлении заказа.\n\n'
            f'Желаем отличного катания и ярких впечатлений!\n\n'
            f'С уважением,\nКоманда Ski Rent'
        )
        try:
            send_mail(
                subject,
                body,
                getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@skirent.kz'),
                [client.email],
                fail_silently=True,
            )
            client.birthday_email_sent_year = year
            client.save(update_fields=['birthday_email_sent_year'])
        except Exception:
            pass