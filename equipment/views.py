from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from rest_framework.viewsets import ModelViewSet

from .models import Equipment, EquipmentType, EquipmentSize
from .serializers import EquipmentSerializer, EquipmentTypeSerializer


# ─────────────────────────────────────────
#  REST API ViewSets
# ─────────────────────────────────────────
class EquipmentViewSet(ModelViewSet):
    queryset = Equipment.objects.all()
    serializer_class = EquipmentSerializer


class EquipmentTypeViewSet(ModelViewSet):
    queryset = EquipmentType.objects.all()
    serializer_class = EquipmentTypeSerializer


# ─────────────────────────────────────────
#  Web pages (moved from web/views.py)
# ─────────────────────────────────────────
@login_required(login_url="login")
def equipment_page(request):
    """Страница снаряжения (только admin/manager)."""
    from rentals.utils import close_expired_rentals, recalculate_inventory_counters

    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")
    close_expired_rentals()
    recalculate_inventory_counters()

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
                    Equipment.objects.create(
                        name=equipment_name, type=et, size=size, status=status,
                        price_per_day=price_per_day, quantity=quantity,
                    )
                    messages.success(request, "Снаряжение добавлено.")
                return redirect("equipment")
    return render(request, "forms/equipment_form.html", {
        "user": request.user,
        "role": request.user.role,
        "is_admin": request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "equipment_types": equipment_types,
        "error": error,
        "equipment": equipment,
    })


@login_required(login_url='login')
def warehouse_view(request):
    """Ведомость остатков снаряжения по категориям."""
    from rentals.utils import recalculate_inventory_counters

    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    recalculate_inventory_counters()

    types = EquipmentType.objects.prefetch_related('equipment__sizes').order_by('name')

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
                    cat_total += sz.quantity
                    cat_rented += sz.quantity_rented
                    cat_avail += avail
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
                cat_total += eq.quantity
                cat_rented += eq.quantity_rented
                cat_avail += avail

        if items:
            report.append({
                'type': eq_type.name,
                'items': items,
                'cat_total': cat_total,
                'cat_rented': cat_rented,
                'cat_avail': cat_avail,
                'positions': len(items),
            })
            grand_total += cat_total
            grand_rented += cat_rented
            grand_avail += cat_avail

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin': request.user.role == 'admin',
        'is_manager': request.user.role in ('admin', 'manager'),
        'is_cashier': request.user.role in ('admin', 'manager', 'cashier'),
        'report': report,
        'grand_total': grand_total,
        'grand_rented': grand_rented,
        'grand_avail': grand_avail,
        'grand_load': round(grand_rented / grand_total * 100) if grand_total else 0,
    }
    return render(request, 'warehouse.html', context)
