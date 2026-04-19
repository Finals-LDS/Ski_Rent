from django.db.models import Sum
from django.utils import timezone
from datetime import date

from .models import Rental, RentalItem
from equipment.models import Equipment



def get_dashboard_stats(date_from=None, date_to=None):
    rentals = Rental.objects.all()

    #фильтр по датам
    if date_from:
        rentals = rentals.filter(start_date__gte=date_from)
    if date_to:
        rentals = rentals.filter(end_date__lte=date_to)

    today = date.today()

    return {
        "total_revenue": rentals.aggregate(Sum("total_price"))["total_price__sum"] or 0,
        "active_rentals": rentals.filter(status='active').count(),
        "completed_rentals": rentals.filter(status='completed').count(),
        "overdue_rentals": rentals.filter(
            end_date__it=today,
            status='active'
        ).count()
    }

def get_inventory_stats():
    equipment = Equipment.objects.all()
    data = []

    for item in equipment:
        in_rent = RentalItem.objects.filter(
            equipment=item,
            rental__status='active'
        ).count()

        data.append({
            "name": item.name,
            "total": 1,
            "available": 1 - in_rent,
            "in_rent": in_rent
        })

    return data

def get_category_stats():
    equipment = equipment.objects.select_related('type')
    result = {}

    for item in equipment:
        category = item.type.name

        if category not in result:
            result[category] = {
                "total": 0,
                "in_rent": 0,
                "available": 0
            }

        result[category]["total"] += 1
        
        is_rented = RentalItem.objects.filter(
            equipment=item,
            rental__status='active'
        ).exists()

        if is_rented:
            result[category]["in_rent"] += 1
        else:
            result[category]["available"] += 1

    return result

def get_top_clients():
    return (
        Rental.objects
        .values("client__full_name")
        .annotate(total_spent=Sum("total_price"))
        .order_by("-total_spent")[:5]
    )


def generate_contract_text(client, rental):
    return f"""
    ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ

    Клиент: {client.full_name}
    Телефон: {client.phone}

    Условия:
    1. Клиент обязуется вернуть оборудование в срок.
    2. В случае повреждения - компенсация.
    3. Оплата производится заранее.
    4. Срок аренды: {rental.start_date} - {rental.end_date}

    Подтверждая договор, вы соглашаетесь со всеми условиями.

    [✓] Я принимаю условия
    """

def can_start_rental(rental):
    try:
        contract = rental.contract
        return contract.status == 'accepted'
    except:
        return False