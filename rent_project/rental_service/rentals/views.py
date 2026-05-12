import hashlib
import logging
import random
import re
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction

from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from clients.models import Client
from equipment.models import Equipment, EquipmentSize

from .models import Contract, Discount, Rental, RentalItem, Signature
from .pdf_utils import generate_contract_pdf
from .serializers import RentalSerializer
from .services import (
    can_start_rental,
    generate_contract_text,
    send_contract_pdf_email,
)
from .utils import (
    ACTIVE_RENTAL_STATUSES,
    build_contract_sms,
    close_expired_rentals,
    normalize_phone,
    recalculate_inventory_counters,
    send_sms,
)


logger = logging.getLogger(__name__)


OTP_CACHE_KEY = "sms_otp_{contract_id}"
OTP_TTL = 120
COOLDOWN_KEY = "sms_cooldown_{contract_id}"
COOLDOWN_TTL = 30


# ═════════════════════════════════════════════════════════════════════════
#  OTP helpers
# ═════════════════════════════════════════════════════════════════════════

def _generate_otp():
    return str(random.randint(100000, 999999))


def _store_otp(contract_id, code):
    cache.set(OTP_CACHE_KEY.format(contract_id=contract_id), code, OTP_TTL)


def _verify_and_clear_otp(contract_id, code):
    key = OTP_CACHE_KEY.format(contract_id=contract_id)
    stored = cache.get(key)
    if stored and stored == code:
        cache.delete(key)
        return True
    return False


def _set_cooldown(contract_id):
    import time
    expire_at = time.time() + COOLDOWN_TTL
    cache.set(COOLDOWN_KEY.format(contract_id=contract_id), expire_at, COOLDOWN_TTL + 5)


def _cooldown_remaining(contract_id):
    import time
    expire_at = cache.get(COOLDOWN_KEY.format(contract_id=contract_id))
    if not expire_at:
        return 0
    return max(0, int(expire_at - time.time()))


# ═════════════════════════════════════════════════════════════════════════
#  REST API
# ═════════════════════════════════════════════════════════════════════════

class RentalViewSet(ModelViewSet):
    queryset = Rental.objects.all()
    serializer_class = RentalSerializer

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        rental = self.get_object()
        rental.status = 'open'
        rental.save(update_fields=['status'])
        return Response({'status': 'activated'})

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        rental = self.get_object()
        rental.status = 'completed'
        rental.save(update_fields=['status'])
        return Response({'status': 'closed'})


class CreateContractView(APIView):
    """POST /api/rentals/contract/create/<rental_id>/ — создать договор для аренды."""

    def post(self, request, rental_id):
        rental = get_object_or_404(Rental, id=rental_id)
        client = rental.client

        contract = Contract.objects.create(
            client=client,
            rental=rental,
            text=generate_contract_text(client, rental),
            status='sent',
        )

        return Response({
            "contract_id": contract.id,
            "text": contract.text,
        })


class StartRentalView(APIView):
    """POST /api/rentals/rental/start/<rental_id>/ — начать аренду (если договор подписан)."""

    def post(self, request, rental_id):
        rental = get_object_or_404(Rental, id=rental_id)
        if not can_start_rental(rental):
            return Response({'error': 'Договор не подписан'}, status=400)
        rental.status = 'rented'
        rental.save(update_fields=['status'])
        return Response({'status': 'Аренда начата'})


class ContractSmsSendView(APIView):
    """POST /api/rentals/contract/<contract_id>/sms/send/ — отправить SMS-OTP."""

    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related("client", "rental")
                            .prefetch_related("rental__items__equipment"),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {"ok": False, "error": "Договор уже подписан"},
                status=drf_status.HTTP_409_CONFLICT,
            )

        send_channel = (request.data.get("channel") or "sms").strip().lower()
        if send_channel not in ("sms", "email"):
            send_channel = "sms"

        phone = contract.client.phone
        email = contract.client.email

        remaining = _cooldown_remaining(contract_id)
        if remaining:
            return Response(
                {
                    "ok": False,
                    "error": f"Подождите {remaining} сек. перед повторной отправкой",
                    "cooldown": remaining,
                },
                status=drf_status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = _generate_otp()
        _store_otp(contract_id, code)

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
                        status=drf_status.HTTP_400_BAD_REQUEST,
                    )

            if used_channel == "sms":
                normalized_phone = normalize_phone(phone)

                # ── SMS 1: копия договора ────────────────────────────
                contract_text = build_contract_sms(contract)
                ok_contract, err_contract = send_sms(normalized_phone, contract_text)
                if not ok_contract:
                    logger.warning(
                        "Не удалось отправить копию договора на %s: %s",
                        normalized_phone, err_contract,
                    )
                    # Не блокируем процесс — OTP всё равно отправляем

                # ── SMS 2: OTP-код для подписания ────────────────────
                ok_otp, err_otp = send_sms(normalized_phone, otp_text_sms)
                if not ok_otp:
                    if email:
                        used_channel = "email"
                        error_message = err_otp
                    else:
                        cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                        return Response(
                            {"ok": False, "error": err_otp or "Ошибка отправки SMS с кодом"},
                            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                        )

        if used_channel == "email":
            if not email:
                cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
                return Response(
                    {"ok": False, "error": "У клиента не указан email для отправки кода"},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

            try:
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
                    status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        if used_channel not in ("sms", "email"):
            cache.delete(OTP_CACHE_KEY.format(contract_id=contract_id))
            return Response(
                {"ok": False, "error": "Не удалось отправить код подтверждения"},
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        _set_cooldown(contract_id)

        response_data = {"ok": True, "channel": used_channel}
        if used_channel == "email" and error_message:
            response_data["fallback_reason"] = error_message
        if settings.DEBUG:
            # В режиме разработки показываем код прямо в интерфейсе
            response_data["dev_otp"] = code

        return Response(response_data)


class ContractSmsVerifyView(APIView):
    """POST /api/rentals/contract/<contract_id>/sms/verify/ — проверить SMS-OTP."""

    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related("client", "rental"),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {"ok": False, "error": "Договор уже подписан"},
                status=drf_status.HTTP_409_CONFLICT,
            )

        code = (request.data.get("code") or "").strip()

        if not _verify_and_clear_otp(contract_id, code):
            return Response(
                {"ok": False, "error": "Неверный или просроченный код"},
                status=drf_status.HTTP_400_BAD_REQUEST,
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
        contract.save(update_fields=['status', 'accepted_at', 'signature_data'])

        # ── Отправка PDF договора на email клиента ──────────────────
        try:
            send_contract_pdf_email(contract)
        except Exception as pdf_exc:
            logger.warning("Не удалось отправить PDF договора: %s", pdf_exc)

        # ── SMS-подтверждение о подписании договора ────────────────
        phone = contract.client.phone
        if phone:
            normalized_phone = normalize_phone(phone)
            signed_str = now.strftime("%d.%m.%Y в %H:%M")
            confirm_text = (
                f"Ski Rent: Договор #{contract_id} подписан {signed_str}.\n"
                f"Клиент: {contract.client.full_name}.\n"
                f"Если вы не подписывали этот договор — обратитесь к оператору."
            )
            ok_c, _err = send_sms(normalized_phone, confirm_text)
            if not ok_c:
                logger.warning(
                    "Не удалось отправить подтверждение подписания на %s",
                    normalized_phone,
                )

        return Response({"ok": True})


class SignCardView(APIView):
    """POST /api/rentals/sign/card/<contract_id>/ — подписать через ЭЦП (NCALayer)."""

    def post(self, request, contract_id):
        contract = get_object_or_404(
            Contract.objects.select_related('client', 'rental'),
            id=contract_id,
        )

        if contract.is_signed:
            return Response(
                {'ok': False, 'error': 'Договор уже подписан', 'current_status': contract.status},
                status=drf_status.HTTP_409_CONFLICT,
            )

        raw_sig = (request.data.get('signature') or '').strip()
        if not raw_sig:
            return Response(
                {'ok': False, 'error': 'Отсутствуют данные подписи (signature)'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        sig_clean = re.sub(r"\s+", "", raw_sig)
        if len(sig_clean) < 80 or not re.match(r"^[A-Za-z0-9+/=]+$", sig_clean):
            return Response(
                {
                    "ok": False,
                    "error": "Подпись отклонена: ожидается полноценный CMS (Base64) от NCALayer после ввода PIN.",
                },
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()

        Signature.objects.create(
            contract=contract,
            operator=request.user if request.user.is_authenticated else None,
            method=Signature.METHOD_CARD,
            raw_signature=raw_sig,
        )

        contract.status = 'signed_card'
        contract.accepted_at = now
        contract.signature_data = raw_sig
        contract.save(update_fields=['status', 'accepted_at', 'signature_data'])

        try:
            send_contract_pdf_email(contract)
        except Exception as pdf_exc:
            logger.warning("Не удалось отправить PDF договора (ЭЦП): %s", pdf_exc)

        return Response({
            'ok':          True,
            'status':      'signed_card',
            'signed_at':   now.isoformat(),
            'contract_id': contract.id,
        })


# ═════════════════════════════════════════════════════════════════════════
#  Web pages (moved from web/views.py)
# ═════════════════════════════════════════════════════════════════════════

@login_required(login_url="login")
def rentals_page(request):
    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    close_expired_rentals()
    recalculate_inventory_counters()

    error = None
    clients = Client.objects.order_by("-created_at")
    equipments = Equipment.objects.order_by("name")

    if request.method == "POST":
        action_name = request.POST.get("action", "create")
        if action_name == "status" and request.user.role == "admin":
            rental = get_object_or_404(Rental, pk=request.POST.get("rental_id"))
            new_status = request.POST.get("new_status", "").strip()
            if new_status in dict(Rental.STATUS_CHOICES):
                rental.status = new_status
                rental.save(update_fields=["status"])
                messages.success(request, "Статус аренды обновлён.")
            return redirect("rentals")
        if action_name == "delete" and request.user.role == "admin":
            rental = get_object_or_404(Rental, pk=request.POST.get("rental_id"))
            rental.delete()
            messages.success(request, "Аренда удалена.")
            return redirect("rentals")

        if action_name == "create" and request.user.role in ("admin", "manager"):
            client_id = request.POST.get("client_id", "").strip()
            days_raw = request.POST.get("days", "1").strip()
            start_date_raw = request.POST.get("start_date", "").strip()
            status_val = request.POST.get("status", "draft").strip()

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
                        "qty": eq_qty,
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
                            status=status_val if status_val in dict(Rental.STATUS_CHOICES) else "draft",
                            start_date=start_d,
                            end_date=end_d,
                            discount=Discount.objects.filter(pk=discount_id).first() if discount_id else None,
                        )

                        for item in items_data:
                            equipment = equipment_map.get(item["eq_id"])
                            if equipment:
                                equipment_size = None
                                if item.get("size"):
                                    equipment_size = EquipmentSize.objects.filter(
                                        equipment=equipment,
                                        size=item["size"].strip()
                                    ).first()

                                RentalItem.objects.create(
                                    rental=rental,
                                    equipment=equipment,
                                    equipment_size=equipment_size,
                                    price_per_day=equipment.price_per_day,
                                    days=days,
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

    from django.db.models import Sum
    active_rentals_total_price = (
        rentals.filter(status__in=ACTIVE_RENTAL_STATUSES)
        .aggregate(total=Sum("total_price"))["total"]
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
        status_val     = request.POST.get("status", "draft").strip()

        item_rows = request.POST.getlist("item_rows")

        items = []
        for n in item_rows:
            eq_id = request.POST.get(f"eq_id_{n}", "").strip()
            qty   = request.POST.get(f"eq_qty_{n}", "1").strip()
            size  = request.POST.get(f"eq_size_{n}", "").strip()
            if eq_id:
                items.append({
                    "eq_id": eq_id,
                    "qty": int(qty) if qty.isdigit() else 1,
                    "size": size,
                })

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
                client = get_object_or_404(Client, pk=client_id)
                start_d = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
                end_d = start_d + timedelta(days=max(days, 1) - 1)
                discount_id = request.POST.get("discount_id", "").strip()

                try:
                    with transaction.atomic():
                        rental = Rental.objects.create(
                            client=client,
                            status=status_val if status_val in dict(Rental.STATUS_CHOICES) else "draft",
                            start_date=start_d,
                            end_date=end_d,
                            discount=Discount.objects.filter(pk=discount_id).first() if discount_id else None,
                        )

                        for item in items:
                            equipment = get_object_or_404(Equipment, pk=item["eq_id"])
                            equipment_size = None
                            if item.get("size"):
                                equipment_size = EquipmentSize.objects.filter(
                                    equipment=equipment,
                                    size=item["size"].strip()
                                ).first()

                            RentalItem.objects.create(
                                rental=rental,
                                equipment=equipment,
                                equipment_size=equipment_size,
                                price_per_day=equipment.price_per_day,
                                days=max(days, 1),
                                quantity=item["qty"],
                            )

                        rental.total_price = rental.calculate_total_price()
                        rental.save(update_fields=["total_price"])

                except ValidationError as e:
                    messages.error(request, e.message)
                    return redirect(request.path)
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
        "discounts":  Discount.objects.order_by("min_days"),
    })


@login_required(login_url="login")
def rental_edit_page(request, rental_id):
    if request.user.role not in ("admin", "manager"):
        return redirect("rentals")
    rental = get_object_or_404(Rental, pk=rental_id)
    error = None
    if request.method == "POST":
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw   = request.POST.get("end_date", "").strip()
        try:
            start_d = date.fromisoformat(start_date_raw) if start_date_raw else None
            end_d   = date.fromisoformat(end_date_raw) if end_date_raw else None
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


@login_required(login_url='login')
def contract_create_web(request, rental_id):
    """Создаёт договор для аренды (если ещё нет) и редиректит на страницу договора."""
    if request.user.role not in ('admin', 'manager', 'cashier'):
        return redirect('dashboard')

    rental = get_object_or_404(Rental.objects.select_related('client'), pk=rental_id)

    if not rental.client:
        messages.error(request, 'У аренды нет клиента — нельзя создать договор.')
        return redirect('rentals')

    try:
        contract = rental.contract
    except Contract.DoesNotExist:
        contract = Contract.objects.create(
            client=rental.client,
            rental=rental,
            text=generate_contract_text(rental.client, rental),
            status='sent',
        )

    return redirect('contract_detail', contract_id=contract.id)


@login_required(login_url='login')
def contract_detail_page(request, contract_id):
    """Страница договора с подписанием через ЭЦП (карт-ридер) или SMS."""
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


@login_required(login_url='login')
def contract_pdf_download(request, contract_id):
    """Скачать PDF договора."""
    if request.user.role not in ('admin', 'manager', 'cashier'):
        return redirect('dashboard')
    contract = get_object_or_404(
        Contract.objects.select_related('client', 'rental'),
        pk=contract_id,
    )
    try:
        pdf_bytes = generate_contract_pdf(contract)
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = (
            f'attachment; filename="contract_{contract.rental.contract_number}.pdf"'
        )
        return resp
    except Exception as exc:
        messages.error(request, f'Ошибка генерации PDF: {exc}')
        return redirect('contract_detail', contract_id=contract_id)
