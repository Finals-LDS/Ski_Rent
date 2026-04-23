from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from rest_framework.response import Response
from equipment.models import Equipment, EquipmentType
from rentals.models import Rental, Discount, PriceModifier, Payment
from .serializers import RentalSerializer, PaymentSerializer
from .models import Contract
from .services import (
    generate_contract_text,
    can_start_rental,
    get_category_stats,
    get_dashboard_stats,
    get_inventory_stats,
    get_top_clients
)
from django.utils import timezone
from rest_framework.decorators import action


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

    @action(detail=True, methods=['post'])
    def activate(self,request, pk=None):
        rental = self.get_object()
        rental.status = 'active'
        rental.save()
        return Response({'status': 'activated'})
    
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        rental = self.get_objects()
        rental.status = 'closed'
        rental.save()
        return Response({'status': 'closed'})


class PaymentViewSet(ModelViewSet):
    queryset = Payment.objects.select_related('client').prefetch_related('items')
    serializer_class = PaymentSerializer


class DashboardView(APIView):
    def get(self, request):
        data = {
            "stats": get_dashboard_stats(),
            "inventory": get_inventory_stats(),
            "categories": get_category_stats(),
            "top_clients": list(get_top_clients())
        }
        return Response(data)
    
class CreateContractView(APIView):
    def post(self, request, rental_id):
        rental = Rental.objects.get(id=rental_id)
        client = rental.client

        contract = Contract.objects.create(
            client=client,
            rental=rental,
            text=generate_contract_text(client, rental),
            status='sent'
        )

        return Response({
            "contract_id": contract.id,
            "text": contract.text
        })
    
class AcceptContractView(APIView):
    def post(self, request, contract_id):
        contract = Contract.objects.get(id=contract_id)

        # проверка: нельзя принять дважды
        if contract.status == 'accepted':
            return Response({"error": "Уже принят"}, status=400)
        
        contract.status = 'accepted'
        contract.accepted_at = timezone.now()

        # сюда можно будет потом подпись засунуть
        contract.signature_data = request.data.get('signature')

        contract.save()

        return Response({"status": "Договор принят"})
    
class SignCardView(APIView):
    """
    POST /api/sign/card/<contract_id>/

    Тело запроса (JSON):
        { "signature": "<base64-XML из NCALayer>" }

    Ответ при успехе:
        { "ok": true, "status": "signed_card", "signed_at": "ISO datetime" }
    """

    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related('client', 'rental'),
            id=contract_id,
        )

        # Нельзя подписать дважды
        if contract.is_signed:
            return Response(
                {'ok': False, 'error': 'Договор уже подписан', 'current_status': contract.status},
                status=http_status.HTTP_409_CONFLICT,
            )

        raw_sig = (request.data.get('signature') or '').strip()
        if not raw_sig:
            return Response(
                {'ok': False, 'error': 'Отсутствуют данные подписи (signature)'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()

        # 1. Сохраняем подпись
        Signature.objects.create(
            contract=contract,
            operator=request.user if request.user.is_authenticated else None,
            method=Signature.METHOD_CARD,
            raw_signature=raw_sig,
        )

        # 2. Обновляем договор
        contract.status         = 'signed_card'
        contract.accepted_at    = now
        contract.signature_data = raw_sig
        contract.save(update_fields=['status', 'accepted_at', 'signature_data'])

        return Response({
            'ok':        True,
            'status':    'signed_card',
            'signed_at': now.isoformat(),
            'contract_id': contract.id,
        })


class StartRentalView(APIView):
    def post(self, request, rental_id):
        rental = get_object_or_404(Rental, id=rental_id)
        if not can_start_rental(rental):
            return Response({'error': 'Договор не подписан'}, status=400)
        rental.status = 'rented'
        rental.save()
        return Response({'status': 'Аренда начата'})
