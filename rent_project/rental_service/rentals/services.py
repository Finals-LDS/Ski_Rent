from datetime import date

from django.db.models import Sum
from django.utils import timezone

from equipment.models import Equipment

from .models import Rental, RentalItem, Contract


RENTAL_ACTIVE = ("open", "booked", "rented")


def get_dashboard_stats(date_from=None, date_to=None):
    rentals = Rental.objects.all()
    if date_from:
        rentals = rentals.filter(start_date__gte=date_from)
    if date_to:
        rentals = rentals.filter(end_date__lte=date_to)

    today = date.today()

    return {
        "total_revenue": rentals.aggregate(Sum("total_price"))["total_price__sum"] or 0,
        "active_rentals": rentals.filter(status__in=RENTAL_ACTIVE).count(),
        "completed_rentals": rentals.filter(status="completed").count(),
        "overdue_rentals": rentals.filter(
            end_date__lt=today,
            status__in=RENTAL_ACTIVE,
        ).count(),
    }


def get_inventory_stats():
    equipment = Equipment.objects.select_related("type")
    data = []

    for item in equipment:
        in_rent = RentalItem.objects.filter(
            equipment=item,
            rental__status__in=RENTAL_ACTIVE,
        ).count()

        data.append(
            {
                "name": item.name,
                "total": 1,
                "available": 1 - in_rent,
                "in_rent": in_rent,
            }
        )

    return data


def get_category_stats():
    qs = Equipment.objects.select_related("type")
    result = {}

    for item in qs:
        category = item.type.name

        if category not in result:
            result[category] = {
                "total": 0,
                "in_rent": 0,
                "available": 0,
            }

        result[category]["total"] += 1

        is_rented = RentalItem.objects.filter(
            equipment=item,
            rental__status__in=RENTAL_ACTIVE,
        ).exists()

        if is_rented:
            result[category]["in_rent"] += 1
        else:
            result[category]["available"] += 1

    return result


def get_top_clients():
    return (
        Rental.objects.values("client__full_name")
        .annotate(total_spent=Sum("total_price"))
        .order_by("-total_spent")[:5]
    )


def generate_contract_text(client, rental):
    items = rental.items.select_related('equipment').all()
    if items.exists():
        lines = []
        for item in items:
            name = item.equipment.name
            size_str = f', размер: {item.size}' if item.size else ''
            qty_str = f', кол-во: {item.quantity}' if item.quantity > 1 else ''
            price_total = item.price_per_day * item.days * item.quantity
            lines.append(
                f'  - {name}{size_str}{qty_str}, '
                f'{item.days} дн. × {item.price_per_day} ₸ = {price_total} ₸'
            )
        equipment_block = '\n'.join(lines)
    else:
        equipment_block = '     - снаряжение не указано'

    return f"""
    ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ

    Клиент: {client.full_name}
    Телефон: {client.phone}
    Снаряжение: {equipment_block}

    Срок аренды: {rental.start_date} - {rental.end_date}
    Итоговая стоимость: {rental.total_price} ₸

    Условия:
    1. Клиент обязуется вернуть оборудование в срок.
    2. В случае повреждения - компенсация.
    3. Оплата производится заранее.

    Подтверждая договор, вы соглашаетесь со всеми условиями.
    
    
    """


def can_start_rental(rental):
    try:
        contract = rental.contract
        return contract.is_signed
    except Contract.DoesNotExist:
        return False
