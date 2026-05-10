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
from equipment.models import Equipment, EquipmentType, EquipmentSize
from rentals.models import (Rental, RentalItem, Discount, PriceModifier, Contract)
from rentals.services import generate_contract_text
from payments.models import (Payment, RefundTransaction)



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


def _recalculate_inventory_counters():
    """Пересчитывает поля quantity_rented по активным арендам."""
    Equipment.objects.update(quantity_rented=0)
    EquipmentSize.objects.update(quantity_rented=0)

    rented_by_equipment = (
        RentalItem.objects.filter(rental__status__in=ACTIVE_RENTAL_STATUSES)
        .values("equipment_id")
        .annotate(total=Sum("quantity"))
    )
    for row in rented_by_equipment:
        Equipment.objects.filter(pk=row["equipment_id"]).update(
            quantity_rented=row["total"] or 0
        )

    rented_by_size = (
        RentalItem.objects.filter(rental__status__in=ACTIVE_RENTAL_STATUSES)
        .exclude(size__isnull=True)
        .exclude(size="")
        .values("equipment_id", "size")
        .annotate(total=Sum("quantity"))
    )
    for row in rented_by_size:
        EquipmentSize.objects.filter(
            equipment_id=row["equipment_id"], size=row["size"]
        ).update(quantity_rented=row["total"] or 0)


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
    _recalculate_inventory_counters()

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
    month_payments_total = (
        Payment.objects.filter(created_at__gte=month_start, created_at__lt=next_month)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    month_refunds_total = (
        RefundTransaction.objects.filter(created_at__gte=month_start, created_at__lt=next_month)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    total_income_month = month_payments_total - month_refunds_total

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

        "recent_refunds": RefundTransaction.objects.filter()
            .select_related("payment__rental__client")
            .order_by("-created_at")[:10],

        "today_payments": Payment.objects.filter(
            created_at__date=timezone.now().date()
        ).select_related("rental__client").order_by("-created_at"),

        "today_income": (
            (
                Payment.objects.filter(
                    created_at__date=timezone.now().date(),
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
            )
            -
            (
                RefundTransaction.objects.filter(
                    created_at__date=timezone.now().date(),
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
            )
        ),

        "today_refunds": RefundTransaction.objects.filter(
            created_at__date=timezone.now().date(),
        ).aggregate(total=Sum("amount"))["total"] or 0,

        "today_count": Payment.objects.filter(
            created_at__date=timezone.now().date()
        ).count(),
    }
    return render(request, "dashboard.html", context)


@login_required(login_url="login")
def clients_page(request):
    """Страница клиентов (только admin/manager)."""
    if request.user.role not in ("admin", "manager", "cashier"):
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
    _recalculate_inventory_counters()

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
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    _close_expired_rentals()
    _recalculate_inventory_counters()

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

        if action == "create" and request.user.role in ("admin", "manager"):
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

                    items_data.append({
                        "eq_id": eq_id,
                        "size": eq_size,
                        "qty": eq_qty
                    })

            if not client_id or not items_data:
                error = "Выберите клиента и добавьте хотя бы одно снаряжение."
            else:
                try:
                    days = int(days_raw)
                    if days < 1:
                        raise ValueError()
                except ValueError:
                    error = "Дней должно быть целым числом >= 1."
                else:
                    client = get_object_or_404(Client, pk=client_id)

                    try:
                        start_d = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
                    except ValueError:
                        error = "Некорректная дата начала."
                        start_d = None

                    if error is None:
                        eq_ids = [i["eq_id"] for i in items_data]
                        equipment_map = {
                            str(e.pk): e for e in Equipment.objects.filter(pk__in=eq_ids)
                        }

                        if not equipment_map:
                            error = "Выбранное снаряжение не найдено."

                    if error is None:
                        end_d = start_d + timedelta(days=days - 1)
                        discount_id = request.POST.get("discount_id", "").strip()

                        rental = Rental.objects.create(
                            client=client,
                            status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                            start_date=start_d,
                            end_date=end_d,
                            discount=Discount.objects.filter(pk=discount_id).first() if discount_id else None,
                        )

                        for item in items_data:
                            equipment = equipment_map.get(item["eq_id"])
                            if equipment:
                                RentalItem.objects.create(
                                    rental=rental,
                                    equipment=equipment,
                                    price_per_day=equipment.price_per_day,
                                    days=days,
                                    size=item["size"] or None,
                                    quantity=item["qty"],
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
    _recalculate_inventory_counters()

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    month_payments_qs = Payment.objects.filter(
        created_at__gte=month_start, created_at__lt=next_month
    )
    month_refunds_qs = RefundTransaction.objects.filter(
        created_at__gte=month_start, created_at__lt=next_month
    )
    month_payments_total = month_payments_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    month_refunds_total = month_refunds_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    total_income_month = month_payments_total - month_refunds_total
    paid_in_month_count = month_payments_qs.count()

    payment_methods_breakdown = (
        month_payments_qs.values("payment_method")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    payment_methods_count = payment_methods_breakdown.count()

    # Группируем платежи по аренде, чтобы не дублировать paid + refund строки
    raw_payments = (
        Payment.objects.select_related("rental__client").order_by("-created_at")
    )

    grouped = {}
    for p in raw_payments:
        rid = p.rental_id
        if rid not in grouped:
            grouped[rid] = {
                "rental": p.rental,
                "client": p.rental.client,
                "net_amount": Decimal("0"),
                "last_method": p.payment_method,
                "last_status": p.status,
                "last_date": p.created_at,
                "last_payment_id": p.id if p.id else None,
                "items": [],
            }

        refunded = RefundTransaction.objects.filter(
            payment=p
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        grouped[rid]["net_amount"] += (p.amount - refunded)
        grouped[rid]["items"].append(p)
        
        if not grouped[rid]["last_payment_id"]:
            grouped[rid]["last_payment_id"] = p.id

        if p.created_at > grouped[rid]["last_date"]:
            grouped[rid]["last_method"] = p.payment_method
            grouped[rid]["last_status"] = p.status
            grouped[rid]["last_date"] = p.created_at
            grouped[rid]["last_payment_id"] = p.id

    payments = list(grouped.values())

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
    # Кассир и админ создают платежи; менеджер — только просмотр
    if request.user.role not in ("admin", "cashier"):
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
    POST → создаёт запись RefundTransaction и обновляет статус платежа
    """
    # Только менеджер и админ могут делать возвраты
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    # Получаем оригинальный платёж — если не найден, вернёт 404
    original_payment = get_object_or_404(Payment, pk=payment_id)

    # Нельзя делать возврат на возврат
    if original_payment.status == "refunded":
        messages.error(request, "Нельзя сделать возврат на уже возвращённый платёж.")
        return redirect("payments")

    # Считаем уже возвращённую сумму по этому платежу
    # Может быть несколько частичных возвратов — суммируем их
    from payments.models import RefundTransaction

    already_refunded = RefundTransaction.objects.filter(
        payment=original_payment
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    max_refund = original_payment.amount - already_refunded
    
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
                    RefundTransaction.objects.create(
                        payment=original_payment,
                        amount=refund_amount,
                        reason=refund_reason or "",
                    )
                    new_refunded_total = (
                        RefundTransaction.objects.filter(payment=original_payment)
                        .aggregate(total=Sum("amount"))["total"]
                        or Decimal("0")
                    )
                    if new_refunded_total >= original_payment.amount:
                        original_payment.status = "refunded"
                    else:
                        original_payment.status = "partially_refunded"
                    original_payment.save(update_fields=["status"])
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
    if request.user.role not in ("admin", "manager"):
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
                Client.objects.create(full_name=full_name, phone=phone, email=email, document_id=document_id)
                messages.success(request, "Клиент добавлен.")
            return redirect("clients")
    return render(request, "forms/client_form.html", {"user": request.user, "role": request.user.role, "is_admin": request.user.role == "admin", "is_manager": request.user.role in ("admin", "manager"), "is_cashier": request.user.role in ("admin", "manager", "cashier"), "error": error, "client": client})


@login_required(login_url="login")
def rental_create_page(request):
    if request.user.role not in ("admin", "manager", "cashier"):
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
                discount_id = request.POST.get("discount_id", "").strip()

                rental = Rental.objects.create(
                    client=client,
                    status=status if status in dict(Rental.STATUS_CHOICES) else "draft",
                    start_date=start_d,
                    end_date=end_d,
                    discount=Discount.objects.filter(pk=discount_id).first() if discount_id else None,
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
    if request.user.role not in ('admin', 'manager', 'cashier'):
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

    # Все роли → страница договора для немедленного подписания
    return redirect('contract_detail', contract_id=contract.id)


@login_required(login_url='login')
def contract_detail_page(request, contract_id):
    """
    Страница договора с подписанием через ЭЦП (карт-ридер) или SMS.
    URL: /contracts/<contract_id>/
    """
    if request.user.role not in ('admin', 'manager', 'cashier'):
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


# ─────────────────────────────────────────
#  ANALYTICS
# ─────────────────────────────────────────
import json
import csv
import io as _io
from datetime import date, timedelta
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

@login_required(login_url='login')
def analytics_view(request):
    """Страница аналитики с дашбордами и экспортом."""
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    _recalculate_inventory_counters()

    from django.db.models.functions import TruncMonth
    from django.db.models import Sum, Count, F
    import json

    today = timezone.now()
    year_start = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    # Revenue by month (current year): платежи минус возвраты
    payments_by_month_qs = (
        Payment.objects
        .filter(created_at__gte=year_start)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )
    refunds_by_month_qs = (
        RefundTransaction.objects
        .filter(created_at__gte=year_start)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )
    month_names_ru = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек']
    payments_map = {r['month'].month: float(r['total']) for r in payments_by_month_qs}
    refunds_map = {r['month'].month: float(r['total']) for r in refunds_by_month_qs}
    rev_map = {m: payments_map.get(m, 0) - refunds_map.get(m, 0) for m in range(1, 13)}
    revenue_labels = json.dumps(month_names_ru)
    revenue_data = json.dumps([rev_map.get(m, 0) for m in range(1, 13)])

    # Rentals by month
    rentals_qs = (
        Rental.objects
        .filter(created_at__gte=year_start)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(cnt=Count('id'))
        .order_by('month')
    )
    rent_map = {r['month'].month: r['cnt'] for r in rentals_qs}
    rentals_by_month = json.dumps([rent_map.get(m, 0) for m in range(1, 13)])

    # Rental status distribution
    status_qs = Rental.objects.values('status').annotate(cnt=Count('id'))
    status_label_map = {'draft':'Черновик','open':'Открыт','booked':'Забронирован',
                        'rented':'Арендован','completed':'Завершён','canceled':'Отменён'}
    status_labels = json.dumps([status_label_map.get(s['status'], s['status']) for s in status_qs])
    status_data = json.dumps([s['cnt'] for s in status_qs])

    # Payment methods
    pm_qs = Payment.objects.values('payment_method').annotate(cnt=Count('id'))
    pm_label_map = {'cash':'Наличные','card':'Карта','transfer':'Перевод'}
    pm_labels = json.dumps([pm_label_map.get(p['payment_method'], p['payment_method']) for p in pm_qs])
    pm_data = json.dumps([p['cnt'] for p in pm_qs])

    # Top equipment
    from rentals.models import RentalItem
    top_equipment = (
        RentalItem.objects
        .values('equipment__name', 'equipment__type__name')
        .annotate(cnt=Count('id'), revenue=Sum(F('price_per_day') * F('days')))
        .order_by('-cnt')[:10]
    )

    # KPI
    total_income_month = (
        Payment.objects.filter(status='paid', created_at__gte=month_start, created_at__lt=next_month)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    total_rentals = Rental.objects.count()
    active_rentals = Rental.objects.filter(status__in=['open','booked','rented']).count()
    total_clients = Client.objects.count()
    total_payments = Payment.objects.count()
    total_equipment = Equipment.objects.count()

    # Birthday today
    td = date.today()
    birthday_clients = Client.objects.filter(birth_date__day=td.day, birth_date__month=td.month)
    birthday_today = birthday_clients.count()

    # Payments journal (last 200)
    payments_journal = Payment.objects.select_related('rental__client').order_by('-created_at')[:200]

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin': request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': True,
        'revenue_labels': revenue_labels,
        'revenue_data': revenue_data,
        'rentals_by_month': rentals_by_month,
        'status_labels': status_labels,
        'status_data': status_data,
        'pm_labels': pm_labels,
        'pm_data': pm_data,
        'top_equipment': top_equipment,
        'total_income_month': total_income_month,
        'total_rentals': total_rentals,
        'active_rentals': active_rentals,
        'total_clients': total_clients,
        'total_payments': total_payments,
        'total_equipment': total_equipment,
        'birthday_today': birthday_today,
        'birthday_clients': birthday_clients,
        'payments_journal': payments_journal,
    }
    return render(request, 'analytics.html', context)


@login_required(login_url='login')
def analytics_export(request):
    """Экспорт отчётов в Excel или CSV."""
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    _recalculate_inventory_counters()

    fmt = request.GET.get('format', 'csv')
    report = request.GET.get('report', 'payments')

    if report == 'inventory':
        from equipment.models import Equipment, EquipmentType
        headers = ['Категория','Наименование','Размер','Статус','Всего','В аренде','Доступно','Загрузка %','Цена/день']
        rows = []
        for eq in Equipment.objects.select_related('type').prefetch_related('sizes').order_by('type__name','name'):
            sizes = list(eq.sizes.all())
            if sizes:
                for sz in sizes:
                    avail = sz.quantity - sz.quantity_rented
                    load = round(sz.quantity_rented / sz.quantity * 100) if sz.quantity else 0
                    rows.append([eq.type.name, eq.name, sz.size,
                                 dict(Equipment.STATUS_CHOICES).get(eq.status, eq.status),
                                 sz.quantity, sz.quantity_rented, avail, f'{load}%', str(eq.price_per_day)])
            else:
                avail = eq.quantity - eq.quantity_rented
                load = round(eq.quantity_rented / eq.quantity * 100) if eq.quantity else 0
                rows.append([eq.type.name, eq.name, eq.size or '—',
                             dict(Equipment.STATUS_CHOICES).get(eq.status, eq.status),
                             eq.quantity, eq.quantity_rented, avail, f'{load}%', str(eq.price_per_day)])
        filename = 'warehouse_report'
    elif report == 'payments':
        qs = Payment.objects.select_related('rental__client').order_by('-created_at')
        headers = ['ID', 'Дата', 'Клиент', 'Договор', 'Сумма', 'Метод', 'Статус']
        rows = [
            [p.id, p.created_at.strftime('%d.%m.%Y %H:%M'),
             p.rental.client.full_name if p.rental.client else '',
             p.rental.contract_number, str(p.amount), p.payment_method, p.status]
            for p in qs
        ]
        filename = 'payments'

    elif report == 'rentals':
        qs = Rental.objects.select_related('client').order_by('-created_at')
        headers = ['ID','Договор','Клиент','Начало','Конец','Статус','Сумма']
        rows = [
            [r.id, r.contract_number, r.client.full_name if r.client else '',
             str(r.start_date or ''), str(r.end_date or ''), r.status, str(r.total_price)]
            for r in qs
        ]
        filename = 'rentals'

    else:  # full
        filename = 'full_report'
        headers = ['Тип', 'ID', 'Дата', 'Клиент', 'Описание', 'Сумма', 'Статус']
        rows = []
        for r in Rental.objects.select_related('client').order_by('-created_at'):
            rows.append(['Аренда', r.id, str(r.created_at.date()),
                         r.client.full_name if r.client else '', r.contract_number, str(r.total_price), r.status])
        for p in Payment.objects.select_related('rental__client').order_by('-created_at'):
            rows.append(['Платёж', p.id, str(p.created_at.date()),
                         p.rental.client.full_name if p.rental.client else '',
                         p.payment_method, str(p.amount), p.status])

    if fmt == 'excel':
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = filename[:31]
            # Header row
            for col, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=h)
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill(start_color='1c2130', end_color='1c2130', fill_type='solid')
                cell.alignment = Alignment(horizontal='center')
            for row_i, row in enumerate(rows, 2):
                for col_i, val in enumerate(row, 1):
                    ws.cell(row=row_i, column=col_i, value=val)
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(len(str(col[0].value or '')), 12) + 4
            buf = _io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            resp = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            resp['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            return resp
        except ImportError:
            pass  # Fall back to CSV if openpyxl not installed

    # CSV fallback
    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(resp)
    writer.writerow(headers)
    writer.writerows(rows)
    return resp


# ─────────────────────────────────────────
#  AI CHAT ENDPOINT
# ─────────────────────────────────────────

# Ключи-заглушки — не отправлять в API
_PLACEHOLDER_KEYS = {
    'sk-ant-your-key-here', 'your-key-here', 'placeholder',
    'sk-ant-api03-placeholder', 'sk-ant-...', 'ваш-ключ',
}

@login_required(login_url='login')
@require_POST
def ai_chat_view(request):
    """ИИ-ассистент Решид для обучения персонала."""
    import json as _json
    try:
        body = _json.loads(request.body)
        user_message = body.get('message', '').strip()
        history = body.get('history', [])
        if not user_message:
            return JsonResponse({'reply': 'Пожалуйста, введите сообщение.'})

        import urllib.request
        import urllib.error
        from django.conf import settings as dj_settings
        from web.models import AppSettings

        # Приоритет: БД → settings.py → переменная окружения
        api_key = (
            AppSettings.get('ANTHROPIC_API_KEY')
            or getattr(dj_settings, 'ANTHROPIC_API_KEY', '')
            or __import__('os').environ.get('ANTHROPIC_API_KEY', '')
        ).strip()

        # Проверяем — не заглушка ли это
        is_placeholder = (
            not api_key
            or api_key in _PLACEHOLDER_KEYS
            or 'your-key' in api_key.lower()
            or 'placeholder' in api_key.lower()
            or api_key == 'sk-ant-your-key-here'
        )

        if is_placeholder:
            return JsonResponse({
                'reply': '⚠️ API-ключ Anthropic не настроен.\n'
                         'Перейдите в **Настройки → ИИ-ассистент** и введите ключ.\n'
                         'Получить ключ: console.anthropic.com',
                'no_key': True,
            })

        system_prompt = """Ты — Решид, ИИ-ассистент горнолыжного проката Ski Rent.
Ты помогаешь сотрудникам (кассирам, менеджерам, администраторам) в работе с CRM-системой.
Отвечай ТОЛЬКО на русском языке. Отвечай кратко, чётко и по делу — максимум 3-4 абзаца.

════════════════════════════════════════
РОЛИ ПОЛЬЗОВАТЕЛЕЙ
════════════════════════════════════════
• admin — полный доступ: пользователи, скидки, модификаторы, удаление всего
• manager — аренды, клиенты, снаряжение, аналитика, возвраты; не может удалять пользователей
• cashier — создание аренд, клиентов, платежей; только просмотр остального

════════════════════════════════════════
СТАТУСЫ АРЕНДЫ (жизненный цикл)
════════════════════════════════════════
draft (Черновик) → open (Открыт) → booked (Забронирован) → rented (Арендован) → completed (Завершён)
                                                                               → canceled (Отменён)
Просроченные аренды (end_date < сегодня) автоматически переходят в "completed" при открытии страниц.
Номер договора генерируется автоматически в формате C001, C002, ...

════════════════════════════════════════
КАК СОЗДАТЬ АРЕНДУ (шаг за шагом)
════════════════════════════════════════
1. Перейти: Аренды → «+ Новая аренда» (или кнопка «Новая аренда» на странице /rentals/new/)
2. Выбрать клиента из списка (или сначала создать его в разделе «Клиенты»)
3. Выбрать начало аренды и количество дней
4. Добавить снаряжение: кнопка «+ Добавить позицию» → выбрать тип + размер + кол-во
5. При необходимости выбрать скидку
6. Нажать «Создать аренду»
После создания аренды можно сформировать договор кнопкой «Договор» в списке аренд.

════════════════════════════════════════
КАК ПОДПИСАТЬ ДОГОВОР
════════════════════════════════════════
1. В списке аренд нажать кнопку «Договор» напротив нужной аренды
2. Откроется страница договора /contracts/<id>/
3. Два способа подписания:
   — SMS OTP: клиент получает 6-значный код на телефон, действует 120 секунд
   — ЭЦП NCALayer: через карт-ридер с ЭЦП (программа NCALayer должна быть запущена)
4. После подписания PDF договора отправляется на email клиента автоматически
5. Статусы договора: draft → sent → signed

════════════════════════════════════════
КАК ПРИНЯТЬ ПЛАТЁЖ
════════════════════════════════════════
Путь: Платежи → «+ Новый платёж»
Поля: выбрать аренду (договор) → метод оплаты → сумма → «Сохранить»
Методы оплаты: Kaspi Bank, Halyk Bank, Наличные
Статусы платежа: paid (оплачен), partially_refunded (частично возвращён), refunded (возвращён)
Кассир и admin могут создавать платежи. Возвраты — только manager и admin.

════════════════════════════════════════
КАК ОФОРМИТЬ ВОЗВРАТ
════════════════════════════════════════
Путь: Платежи → кнопка «Возврат» напротив нужного платежа → /payments/<id>/refund/
Поля: сумма возврата (не больше остатка), способ возврата, причина
Нельзя сделать возврат на платёж со статусом «refunded» (уже полностью возвращён).

════════════════════════════════════════
КЛИЕНТЫ
════════════════════════════════════════
Поля: ФИО (обязательно), телефон (обязательно), email, ИИН, номер документа, дата рождения
Клиентов создают: admin, manager, cashier
Путь: Клиенты → «+ Новый клиент» или /clients/new/
Именинники (дата рождения сегодня) видны в разделе Аналитика. Им можно отправить email со скидкой 15% кнопкой «Отправить поздравления».

════════════════════════════════════════
СНАРЯЖЕНИЕ
════════════════════════════════════════
Поля: тип, название, размер, статус, цена/день, количество
Статусы: available (доступно), rented (в аренде), repair (на ремонте)
Если у снаряжения есть размеры — они управляются через EquipmentSize (размер + кол-во).
Путь добавления: Снаряжение → «+ Добавить» или /equipment/new/
Ведомость остатков по категориям — страница «Склад» /warehouse/
Счётчики quantity_rented пересчитываются автоматически при открытии страниц.

════════════════════════════════════════
СКИДКИ И МОДИФИКАТОРЫ ЦЕН (только admin)
════════════════════════════════════════
Скидки — на странице Дашборд (вкладка «Скидки»): название + % + минимум дней.
Применяются при создании аренды: поле «Скидка» → автоматически вычитается из суммы.
Модификаторы (weekday/holiday multiplier) — там же, множители для дней недели и праздников.

════════════════════════════════════════
АНАЛИТИКА (admin / manager)
════════════════════════════════════════
Страница /analytics/ содержит:
— Выручка по месяцам (платежи минус возвраты)
— Количество аренд по месяцам
— Распределение по статусам аренд
— Методы оплаты (круговая диаграмма)
— Топ-10 снаряжения по количеству аренд
— Журнал последних 200 платежей
Экспорт в Excel (.xlsx) и CSV: кнопки «Экспорт» на странице аналитики.
Отчёты: платежи, аренды, ведомость склада, полный отчёт.

════════════════════════════════════════
НАСТРОЙКИ (только admin)
════════════════════════════════════════
Страница /settings/ — сохранить/проверить ключ Anthropic API для ИИ-ассистента.
Ключ хранится в таблице AppSettings (ключ ANTHROPIC_API_KEY).
Там же кнопка «Проверить подключение» — отправляет тестовый запрос к API.

════════════════════════════════════════
ЧАСТЫЕ ПРОБЛЕМЫ
════════════════════════════════════════
• «Нельзя создать аренду» — возможно, не выбран клиент или не добавлено снаряжение
• «Снаряжение недоступно» — проверьте quantity_available на странице Склад
• «Договор уже существует» — у этой аренды уже есть договор, нажмите «Договор» для просмотра
• «SMS не приходит» — проверьте SMSC_LOGIN/SMSC_PASSWORD в .env; код действует 120 секунд
• «PDF не генерируется» — нужна библиотека reportlab (pip install reportlab)
• ИИ не отвечает — перейдите в /settings/ и проверьте/сохраните ANTHROPIC_API_KEY

Если вопрос не относится к работе Ski Rent CRM, вежливо объясни что ты специализируешься на этой системе."""

        messages_payload = []
        for h in history[-8:]:
            if h.get('role') in ('user', 'assistant') and h.get('content', '').strip():
                messages_payload.append({'role': h['role'], 'content': str(h['content'])[:1000]})
        messages_payload.append({'role': 'user', 'content': user_message})

        req_data = _json.dumps({
            'model': 'claude-3-haiku-20240307',
            'max_tokens': 700,
            'system': system_prompt,
            'messages': messages_payload,
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=req_data,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = _json.loads(resp.read().decode('utf-8'))

        reply = result.get('content', [{}])[0].get('text', 'Нет ответа.')
        return JsonResponse({'reply': reply})

    except urllib.error.HTTPError as e:
        code = e.code
        if code == 401:
            return JsonResponse({
                'reply': '❌ Неверный API-ключ Anthropic (ошибка 401).\n'
                         'Перейдите в /settings/ и введите корректный ключ.',
                'no_key': True,
            })
        elif code == 429:
            return JsonResponse({'reply': '⏳ Превышен лимит запросов к API. Попробуйте через несколько секунд.'})
        else:
            return JsonResponse({'reply': f'Ошибка API: {code}. Проверьте ключ в настройках.'})
    except Exception as exc:
        return JsonResponse({'reply': f'Ошибка соединения: {exc}. Проверьте доступ к интернету.'}, status=200)


# ─────────────────────────────────────────
#  BIRTHDAY EMAIL TRIGGER (web)
# ─────────────────────────────────────────
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


# ─────────────────────────────────────────
#  CONTRACT PDF DOWNLOAD
# ─────────────────────────────────────────
@login_required(login_url='login')
def contract_pdf_download(request, contract_id):
    """Скачать PDF договора."""
    if request.user.role not in ('admin', 'manager', 'cashier'):
        return redirect('dashboard')
    from rentals.models import Contract as ContractModel
    contract = get_object_or_404(ContractModel.objects.select_related('client', 'rental'), pk=contract_id)
    try:
        from rentals.pdf_utils import generate_contract_pdf
        pdf_bytes = generate_contract_pdf(contract)
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="contract_{contract.rental.contract_number}.pdf"'
        return resp
    except Exception as exc:
        messages.error(request, f'Ошибка генерации PDF: {exc}')
        return redirect('contract_detail', contract_id=contract_id)


def send_contract_pdf_email(contract):
    """Вспомогательная функция: отправить PDF договора на email клиента."""
    try:
        from rentals.pdf_utils import generate_contract_pdf
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings as dj_settings

        if not contract.client.email:
            return False

        pdf_bytes = generate_contract_pdf(contract)
        subject = f'Договор аренды № {contract.rental.contract_number} — Ski Rent'
        body = (
            f'Уважаемый(ая) {contract.client.full_name},\n\n'
            f'Ваш договор аренды № {contract.rental.contract_number} подписан.\n'
            f'PDF-копия договора прикреплена к этому письму.\n\n'
            f'С уважением,\nКоманда Ski Rent'
        )
        msg = EmailMultiAlternatives(
            subject=subject, body=body,
            from_email=dj_settings.DEFAULT_FROM_EMAIL,
            to=[contract.client.email],
        )
        msg.attach(
            f'contract_{contract.rental.contract_number}.pdf',
            pdf_bytes, 'application/pdf',
        )
        msg.send(fail_silently=True)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────
#  APP SETTINGS PAGE (API ключи и настройки)
# ─────────────────────────────────────────
@login_required(login_url='login')
def app_settings_view(request):
    """Страница настроек приложения — только для admin."""
    if request.user.role != 'admin':
        return redirect('dashboard')

    from web.models import AppSettings
    import os

    msg_ok = msg_err = None

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'save_anthropic_key':
            key = request.POST.get('anthropic_key', '').strip()
            if key:
                AppSettings.set(
                    'ANTHROPIC_API_KEY', key,
                    note='Ключ Anthropic API для ИИ-ассистента Решид'
                )
                msg_ok = 'API-ключ Anthropic сохранён. ИИ-ассистент готов к работе!'
            else:
                AppSettings.set('ANTHROPIC_API_KEY', '')
                msg_ok = 'API-ключ очищен.'

        elif action == 'test_anthropic_key':
            import urllib.request, urllib.error, json as _json
            api_key = (
                AppSettings.get('ANTHROPIC_API_KEY')
                or getattr(__import__('django.conf', fromlist=['settings']).settings, 'ANTHROPIC_API_KEY', '')
            )
            if not api_key:
                msg_err = 'API-ключ не задан.'
            else:
                try:
                    req_data = _json.dumps({
                        'model': 'claude-3-haiku-20240307',
                        'max_tokens': 20,
                        'messages': [{'role': 'user', 'content': 'ping'}],
                    }).encode()
                    req = urllib.request.Request(
                        'https://api.anthropic.com/v1/messages',
                        data=req_data,
                        headers={
                            'Content-Type': 'application/json',
                            'x-api-key': api_key,
                            'anthropic-version': '2023-06-01',
                        },
                        method='POST',
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        _json.loads(resp.read())
                    msg_ok = '✅ Подключение к Anthropic API успешно! ИИ-ассистент работает.'
                except urllib.error.HTTPError as e:
                    try:
                        err_body = _json.loads(e.read().decode('utf-8', errors='replace'))
                        err_detail = err_body.get('error', {}).get('message', str(err_body))
                    except Exception:
                        err_detail = '(не удалось прочитать ответ)'
                    msg_err = f'❌ Ошибка {e.code}: {err_detail}'
                except Exception as ex:
                    msg_err = f'❌ Ошибка соединения: {ex}'

    # Current stored key (masked)
    stored_key = AppSettings.get('ANTHROPIC_API_KEY', '')
    masked_key = ''
    if stored_key:
        masked_key = stored_key[:12] + '•' * max(0, len(stored_key) - 16) + stored_key[-4:] if len(stored_key) > 16 else '•' * len(stored_key)

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin': True,
        'is_manager': True,
        'is_cashier': True,
        'msg_ok': msg_ok,
        'msg_err': msg_err,
        'has_anthropic_key': bool(stored_key),
        'masked_key': masked_key,
    }
    return render(request, 'app_settings.html', context)


# ─────────────────────────────────────────
#  ВЕДОМОСТЬ СКЛАДА
# ─────────────────────────────────────────
@login_required(login_url='login')
def warehouse_view(request):
    """Ведомость остатков снаряжения по категориям."""
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    _recalculate_inventory_counters()

    from django.db.models import Sum, Count
    from equipment.models import Equipment, EquipmentType, EquipmentSize

    # Build grouped data
    types = EquipmentType.objects.prefetch_related(
        'equipment__sizes'
    ).order_by('name')

    report = []
    grand_total = grand_rented = grand_avail = 0

    for eq_type in types:
        items = []
        cat_total = cat_rented = cat_avail = 0

        for eq in eq_type.equipment.all().order_by('name'):
            sizes = list(eq.sizes.all().order_by('size'))
            if sizes:
                for sz in sizes:
                    avail = sz.quantity - sz.quantity_rented
                    load_pct = round(sz.quantity_rented / sz.quantity * 100) if sz.quantity else 0
                    items.append({
                        'name': eq.name,
                        'size': sz.size,
                        'status': eq.status,
                        'total': sz.quantity,
                        'rented': sz.quantity_rented,
                        'available': avail,
                        'load_pct': load_pct,
                        'price': eq.price_per_day,
                    })
                    cat_total  += sz.quantity
                    cat_rented += sz.quantity_rented
                    cat_avail  += avail
            else:
                avail = eq.quantity - eq.quantity_rented
                load_pct = round(eq.quantity_rented / eq.quantity * 100) if eq.quantity else 0
                items.append({
                    'name': eq.name,
                    'size': eq.size or '—',
                    'status': eq.status,
                    'total': eq.quantity,
                    'rented': eq.quantity_rented,
                    'available': avail,
                    'load_pct': load_pct,
                    'price': eq.price_per_day,
                })
                cat_total  += eq.quantity
                cat_rented += eq.quantity_rented
                cat_avail  += avail

        if items:
            report.append({
                'type': eq_type.name,
                'items': items,
                'cat_total': cat_total,
                'cat_rented': cat_rented,
                'cat_avail': cat_avail,
                'positions': len(items),
            })
            grand_total  += cat_total
            grand_rented += cat_rented
            grand_avail  += cat_avail

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin':   request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': request.user.role in ('admin', 'manager', 'cashier'),
        'report':       report,
        'grand_total':  grand_total,
        'grand_rented': grand_rented,
        'grand_avail':  grand_avail,
        'grand_load': round(grand_rented / grand_total * 100) if grand_total else 0,
    }
    return render(request, 'warehouse.html', context)


# ─────────────────────────────────────────
#  ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# ─────────────────────────────────────────
@login_required(login_url='login')
def profile_view(request):
    """Страница редактирования своего профиля — для всех ролей."""
    msg_ok = msg_err = None

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()
            last_name  = request.POST.get('last_name', '').strip()
            email      = request.POST.get('email', '').strip()
            if not first_name and not last_name:
                msg_err = 'Введите хотя бы имя или фамилию.'
            else:
                request.user.first_name = first_name
                request.user.last_name  = last_name
                request.user.email      = email
                request.user.save(update_fields=['first_name', 'last_name', 'email'])
                msg_ok = 'Профиль успешно обновлён!'

        elif action == 'change_password':
            from django.contrib.auth import update_session_auth_hash
            current  = request.POST.get('current_password', '')
            new_pw   = request.POST.get('new_password', '')
            confirm  = request.POST.get('confirm_password', '')
            if not request.user.check_password(current):
                msg_err = 'Неверный текущий пароль.'
            elif len(new_pw) < 6:
                msg_err = 'Новый пароль должен быть не менее 6 символов.'
            elif new_pw != confirm:
                msg_err = 'Пароли не совпадают.'
            else:
                request.user.set_password(new_pw)
                request.user.save()
                update_session_auth_hash(request, request.user)
                msg_ok = 'Пароль успешно изменён!'

    context = {
        'user':       request.user,
        'role':       request.user.role,
        'is_admin':   request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': request.user.role in ('admin', 'manager', 'cashier'),
        'msg_ok':  msg_ok,
        'msg_err': msg_err,
    }
    return render(request, 'profile.html', context)
