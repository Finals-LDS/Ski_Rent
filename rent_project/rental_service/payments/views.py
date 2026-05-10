from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from rest_framework.viewsets import ModelViewSet

from .models import Payment, RefundTransaction
from .serializers import PaymentSerializer


# ─────────────────────────────────────────
#  REST API ViewSet
# ─────────────────────────────────────────
class PaymentViewSet(ModelViewSet):
    queryset = Payment.objects.select_related('rental__client')
    serializer_class = PaymentSerializer


# ─────────────────────────────────────────
#  Web pages (moved from web/views.py)
# ─────────────────────────────────────────
@login_required(login_url="login")
def payments_page(request):
    """Страница платежей (admin/manager/cashier)."""
    from rentals.utils import close_expired_rentals, recalculate_inventory_counters

    if request.user.role not in ("admin", "manager", "cashier"):
        return redirect("dashboard")
    close_expired_rentals()
    recalculate_inventory_counters()

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
        "error": None,
    }
    return render(request, "payments.html", context)


@login_required(login_url="login")
def payment_create_page(request):
    """
    GET  → показывает форму
    POST → создаёт Payment в базе
    """
    from rentals.models import Rental

    # Кассир и админ создают платежи; менеджер — только просмотр
    if request.user.role not in ("admin", "cashier"):
        return redirect("dashboard")

    # Серверный whitelist методов оплаты — защита от подделки запроса
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

        if not rental_id or not payment_method or not amount_raw:
            error = "Заполните обязательные поля: договор, метод оплаты и сумма."
        elif payment_method not in ALLOWED_METHODS:
            error = "Выберите корректный метод оплаты."
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
                    payment_method=ALLOWED_METHODS[payment_method],
                    status="paid",
                )
                messages.success(request, "Платёж добавлен.")
                return redirect("payments")

    context = {
        "user":       request.user,
        "role":       request.user.role,
        "is_admin":   request.user.role == "admin",
        "is_manager": request.user.role in ("admin", "manager"),
        "is_cashier": request.user.role in ("admin", "manager", "cashier"),
        "rentals_for_select": Rental.objects.filter(
            client__isnull=False
        ).select_related("client").order_by("-created_at"),
        "error": error,
    }
    return render(request, "forms/payment_form.html", context)


@login_required(login_url="login")
def payment_refund_page(request, payment_id):
    """Страница возврата средств по конкретному платежу."""
    if request.user.role not in ("admin", "manager"):
        return redirect("dashboard")

    original_payment = get_object_or_404(Payment, pk=payment_id)

    if original_payment.status == "refunded":
        messages.error(request, "Нельзя сделать возврат на уже возвращённый платёж.")
        return redirect("payments")

    already_refunded = RefundTransaction.objects.filter(
        payment=original_payment
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    max_refund = original_payment.amount - already_refunded

    error = None

    if request.method == "POST":
        refund_amount_raw = request.POST.get("refund_amount", "").strip()
        refund_method     = request.POST.get("refund_method", "").strip()
        refund_reason     = request.POST.get("refund_reason", "").strip()

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
