import re
import logging
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from equipment.models import Equipment, EquipmentType
from rentals.models import Rental, Discount, PriceModifier, Payment
from .serializers import RentalSerializer, PaymentSerializer
from .models import Contract, Signature, Rental
from .services import (
    generate_contract_text,
    can_start_rental,
    get_category_stats,
    get_dashboard_stats,
    get_inventory_stats,
    get_top_clients
)
from django.utils import timezone
from django.core.cache import cache
from rest_framework.decorators import action
import hashlib

import random
from django.conf import settings
from rest_framework.views import APIView
from .utils import send_sms, normalize_phone, build_contract_sms
import hashlib
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

OTP_CACHE_KEY = "sms_otp_{contract_id}"
OTP_TTL = 120
COOLDOWN_KEY = "sms_cooldown_{contract_id}"
COOLDOWN_TTL = 30


def generate_otp():
    return str(random.randint(100000, 999999))


def store_otp(contract_id, code):
    cache.set(OTP_CACHE_KEY.format(contract_id=contract_id), code, OTP_TTL)


def verify_and_clear_otp(contract_id, code):
    key = OTP_CACHE_KEY.format(contract_id=contract_id)
    stored = cache.get(key)
    if stored and stored == code:
        cache.delete(key)
        return True
    return False


def set_cooldown(contract_id):
    import time
    # Сохраняем время истечения, а не просто True
    expire_at = time.time() + COOLDOWN_TTL
    cache.set(COOLDOWN_KEY.format(contract_id=contract_id), expire_at, COOLDOWN_TTL + 5)


def cooldown_remaining(contract_id):
    import time
    expire_at = cache.get(COOLDOWN_KEY.format(contract_id=contract_id))
    if not expire_at:
        return 0
    return max(0, int(expire_at - time.time()))


class ContractSmsSendView(APIView):
    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related("client", "rental")
                            .prefetch_related("rental__items__equipment"),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {"ok": False, "error": "Договор уже подписан"},
                status=status.HTTP_409_CONFLICT,
            )

        send_channel = (request.data.get("channel") or "sms").strip().lower()
        if send_channel not in ("sms", "email"):
            send_channel = "sms"

        phone = contract.client.phone
        email = contract.client.email

        remaining = cooldown_remaining(contract_id)
        if remaining:
            return Response(
                {
                    "ok": False,
                    "error": f"Подождите {remaining} сек. перед повторной отправкой",
                    "cooldown": remaining,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = generate_otp()
        store_otp(contract_id, code)

        otp_text_sms = (
            f"Ski Rent: Договор #{contract_id}\n"
            f"Код подписания: {code}\n"
            f"Никому не сообщайте этот код.\n"
            f"Действителен 2 минуты."
        )

        otp_text_email = (
            f"Код подтверждения для подписания договора #{contract_id}: {code}\n\n"
            f"Срок действия кода: 2 минуты.\n"
            f"Если вы не запрашивали подписание, просто проигнорируйте это письмо."
        )

        used_channel = send_channel
        error_message = None

        if send_channel == "sms":
            if not phone:
                if email:
                    used_channel = "email"
                else:
                    cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                    return Response(
                        {"ok": False, "error": "У клиента не указан номер телефона или email"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            if used_channel == "sms":
                normalized_phone = normalize_phone(phone)

                # ── SMS 1: копия договора ─────────────────────────────────────
                contract_text = build_contract_sms(contract)
                ok_contract, err_contract = send_sms(normalized_phone, contract_text)
                if not ok_contract:
                    logger.warning(
                        "Не удалось отправить копию договора на %s: %s",
                        normalized_phone, err_contract,
                    )
                    # Не блокируем процесс — OTP всё равно отправляем

                # ── SMS 2: OTP-код для подписания ─────────────────────────────
                ok_otp, err_otp = send_sms(normalized_phone, otp_text_sms)
                if not ok_otp:
                    if email:
                        used_channel = "email"
                        error_message = err_otp
                    else:
                        cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                        return Response(
                            {"ok": False, "error": err_otp or "Ошибка отправки SMS с кодом"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE,
                        )

        if used_channel == "email":
            if not email:
                cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                return Response(
                    {"ok": False, "error": "У клиента не указан email для отправки кода"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                from django.core.mail import EmailMultiAlternatives
                # Тело письма — текст договора + OTP-код
                full_message = (
                    f"Предварительная версия договора аренды:\n\n"
                    f"{contract.text}\n\n"
                    f"{'='*60}\n"
                    f"{otp_text_email}"
                )
                html_body = (
                    f"<pre style='font-family:monospace;font-size:13px;white-space:pre-wrap'>"
                    f"{contract.text}</pre>"
                    f"<hr>"
                    f"<p><strong>Код подтверждения для подписания договора #{contract_id}: "
                    f"<span style='font-size:24px;color:#4facfe'>{code}</span></strong></p>"
                    f"<p style='color:#888'>Срок действия: 2 минуты. Никому не сообщайте этот код.</p>"
                )
                msg = EmailMultiAlternatives(
                    subject=f"Ski Rent: договор #{contract_id} — предпросмотр и код подписания",
                    body=full_message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    to=[email],
                )
                msg.attach_alternative(html_body, "text/html")
                msg.send(fail_silently=False)
            except Exception as exc:
                logger.warning("Не удалось отправить OTP на email %s: %s", email, exc)
                cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                error_text = "Ошибка отправки кода на email"
                if settings.DEBUG:
                    error_text = f"{error_text}: {exc}"
                return Response(
                    {"ok": False, "error": error_text},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        if used_channel not in ("sms", "email"):
            cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
            return Response(
                {"ok": False, "error": "Не удалось отправить код подтверждения"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        set_cooldown(contract_id)

        response_data = {"ok": True, "channel": used_channel}
        if used_channel == "email" and error_message:
            response_data["fallback_reason"] = error_message
        if settings.DEBUG:
            # В режиме разработки показываем код прямо в интерфейсе
            response_data["dev_otp"] = code

        return Response(response_data)


class ContractSmsVerifyView(APIView):
    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related("client", "rental"),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {"ok": False, "error": "Договор уже подписан"},
                status=status.HTTP_409_CONFLICT,
            )

        code = (request.data.get("code") or "").strip()

        if not verify_and_clear_otp(contract_id, code):
            return Response(
                {"ok": False, "error": "Неверный или просроченный код"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_sig = "sms_" + hashlib.sha256(code.encode()).hexdigest()
        now = timezone.now()

        Signature.objects.create(
            contract=contract,
            operator=request.user if request.user.is_authenticated else None,
            method=Signature.METHOD_SMS,
            raw_signature=raw_sig,
        )

        contract.status = "signed_sms"
        contract.accepted_at = now
        contract.signature_data = raw_sig
        contract.save()

        # ── Отправка PDF договора на email клиента ─────────────────────────────
        try:
            from web.views import send_contract_pdf_email
            send_contract_pdf_email(contract)
        except Exception as pdf_exc:
            logger.warning("Не удалось отправить PDF договора: %s", pdf_exc)

        # ── SMS-подтверждение о подписании договора ───────────────────────────
        phone = contract.client.phone
        if phone:
            normalized_phone = normalize_phone(phone)
            signed_str = now.strftime("%d.%m.%Y в %H:%M")
            confirm_text = (
                f"Ski Rent: Договор #{contract_id} подписан {signed_str}.\n"
                f"Клиент: {contract.client.full_name}.\n"
                f"Если вы не подписывали этот договор — обратитесь к оператору."
            )
            ok_c, _ = send_sms(normalized_phone, confirm_text)
            if not ok_c:
                logger.warning(
                    "Не удалось отправить подтверждение подписания на %s",
                    normalized_phone,
                )

        return Response({"ok": True})


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
    
    
class SignCardView(APIView):
    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related('client', 'rental'),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {'ok': False, 'error': 'Договор уже подписан', 'current_status': contract.status},
                status=status.HTTP_409_CONFLICT,
            )

        raw_sig = (request.data.get('signature') or '').strip()
        if not raw_sig:
            return Response(
                {'ok': False, 'error': 'Отсутствуют данные подписи (signature)'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sig_clean = re.sub(r"\s+", "", raw_sig)
        if len(sig_clean) < 80 or not re.match(r"^[A-Za-z0-9+/=]+$", sig_clean):
            return Response(
                {
                    "ok": False,
                    "error": "Подпись отклонена: ожидается полноценный CMS (Base64) от NCALayer после ввода PIN.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()

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

        # ── Отправка PDF договора на email клиента ─────────────────────────────
        try:
            from web.views import send_contract_pdf_email
            send_contract_pdf_email(contract)
        except Exception as pdf_exc:
            logger.warning("Не удалось отправить PDF договора (ЭЦП): %s", pdf_exc)

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
