from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from rest_framework.response import Response

from equipment.models import Equipment, EquipmentType
from rentals.models import Rental, Discount, PriceModifier, Payment
from .serializers import RentalSerializer, PaymentSerializer


ACTIVE_RENTAL_STATUSES = ("open", "booked", "rented")


def dashboard(request):
    # Статистика
    equipment_count = Equipment.objects.aggregate(total=Sum("quantity"))["total"] or 0
    active_rentals_count = Rental.objects.filter(
        status__in=ACTIVE_RENTAL_STATUSES
    ).count()
    total_income = (
        Payment.objects.filter(status="paid").aggregate(total=Sum("amount"))["total"]
        or 0
    )

    # Черновики
    draft_rentals = Rental.objects.filter(status="draft").select_related("client").order_by(
        "-updated_at"
    )

    # Список договоров (не черновики)
    rentals_list = Rental.objects.exclude(status="draft").select_related("client").order_by(
        "-created_at"
    )

    # Аналитика по категориям
    equipment_types = EquipmentType.objects.prefetch_related("equipment").all()
    analytics = []
    for et in equipment_types:
        items = et.equipment.all()
        total = items.aggregate(total=Sum("quantity"))["total"] or 0
        rented = items.aggregate(total=Sum("quantity_rented"))["total"] or 0
        available = total - rented
        analytics.append(
            {"name": et.name, "total": total, "available": available, "rented": rented}
        )

    context = {
        "equipment_count": equipment_count,
        "active_rentals_count": active_rentals_count,
        "total_income": total_income,
        "draft_rentals": draft_rentals,
        "rentals_list": rentals_list,
        "analytics": analytics,
    }
    return render(request, "dashboard/dashboard.html", context)


def create_draft(request):
    Rental.objects.create(status="draft")
    return redirect("dashboard")


def delete_rental(request, pk):
    rental = get_object_or_404(Rental, pk=pk)
    rental.delete()
    return redirect("dashboard")


def change_status(request, pk):
    rental = get_object_or_404(Rental, pk=pk)
    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in dict(Rental.STATUS_CHOICES):
            rental.status = new_status
            rental.save(update_fields=["status"])
    return redirect("dashboard")


def settings_view(request):
    equipment_list = Equipment.objects.select_related("type").all()
    discounts = Discount.objects.all()
    modifier = PriceModifier.objects.first()

    if request.method == "POST":
        weekday = request.POST.get("weekday_multiplier")
        holiday = request.POST.get("holiday_multiplier")
        if modifier:
            modifier.weekday_multiplier = weekday
            modifier.holiday_multiplier = holiday
            modifier.save()
        else:
            PriceModifier.objects.create(
                weekday_multiplier=weekday, holiday_multiplier=holiday
            )
        return redirect("settings")

    context = {"equipment_list": equipment_list, "discounts": discounts, "modifier": modifier}
    return render(request, "dashboard/settings.html", context)


class RentalViewSet(ModelViewSet):
    queryset = Rental.objects.all()
    serializer_class = RentalSerializer


class PaymentViewSet(ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer


class DashboardView(APIView):
    def get(self, request):
        return Response({"total_rentals": Rental.objects.count()})