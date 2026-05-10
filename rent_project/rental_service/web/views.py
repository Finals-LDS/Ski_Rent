"""
Cross-cutting web views: аутентификация, дашборд, аналитика, ИИ-ассистент, настройки.
Доменно-специфичные страницы (clients/equipment/rentals/payments/users)
живут в соответствующих приложениях.
"""
import csv
import io as _io
import json as _json
import logging
import urllib.error
import urllib.request
import urllib.parse
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Client
from equipment.models import Equipment, EquipmentType
from payments.models import Payment, RefundTransaction
from rentals.models import Discount, PriceModifier, Rental, RentalItem
from rentals.utils import (
    ACTIVE_RENTAL_STATUSES,
    close_expired_rentals,
    recalculate_inventory_counters,
)
from .models import AppSettings


logger = logging.getLogger(__name__)

# OpenRouter fallback models (stable)
OPENROUTER_MODELS = [
    'mistralai/mistral-7b-instruct:free',
    'meta-llama/llama-3.1-8b-instruct',
    'gryphe/mythomax-l2-13b',
]
User = get_user_model()

ROLE_DASHBOARDS = {
    "admin": "dashboard",
    "manager": "dashboard",
    "cashier": "dashboard",
}


# ═════════════════════════════════════════════════════════════════════════
#  AUTH
# ═════════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═════════════════════════════════════════════════════════════════════════

@login_required(login_url="login")
def dashboard(request):
    """Главный дашборд."""
    user = request.user
    close_expired_rentals()
    recalculate_inventory_counters()

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

    active_rentals_qs = Rental.objects.filter(status__in=ACTIVE_RENTAL_STATUSES)
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


# ═════════════════════════════════════════════════════════════════════════
#  ANALYTICS
# ═════════════════════════════════════════════════════════════════════════

@login_required(login_url='login')
def analytics_view(request):
    """Страница аналитики с дашбордами и экспортом."""
    if request.user.role not in ('admin', 'manager'):
        return redirect('dashboard')
    recalculate_inventory_counters()

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
    month_names_ru = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                      'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
    payments_map = {r['month'].month: float(r['total']) for r in payments_by_month_qs}
    refunds_map = {r['month'].month: float(r['total']) for r in refunds_by_month_qs}
    rev_map = {m: payments_map.get(m, 0) - refunds_map.get(m, 0) for m in range(1, 13)}
    revenue_labels = _json.dumps(month_names_ru)
    revenue_data = _json.dumps([rev_map.get(m, 0) for m in range(1, 13)])

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
    rentals_by_month = _json.dumps([rent_map.get(m, 0) for m in range(1, 13)])

    # Rental status distribution
    status_qs = Rental.objects.values('status').annotate(cnt=Count('id'))
    status_label_map = {
        'draft': 'Черновик', 'open': 'Открыт', 'booked': 'Забронирован',
        'rented': 'Арендован', 'completed': 'Завершён', 'canceled': 'Отменён',
    }
    status_labels = _json.dumps(
        [status_label_map.get(s['status'], s['status']) for s in status_qs]
    )
    status_data = _json.dumps([s['cnt'] for s in status_qs])

    # Payment methods
    pm_qs = Payment.objects.values('payment_method').annotate(cnt=Count('id'))
    pm_label_map = {'cash': 'Наличные', 'card': 'Карта', 'transfer': 'Перевод'}
    pm_labels = _json.dumps(
        [pm_label_map.get(p['payment_method'], p['payment_method']) for p in pm_qs]
    )
    pm_data = _json.dumps([p['cnt'] for p in pm_qs])

    # Top equipment
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
    active_rentals = Rental.objects.filter(status__in=['open', 'booked', 'rented']).count()
    total_clients = Client.objects.count()
    total_payments = Payment.objects.count()
    total_equipment = Equipment.objects.count()

    # Birthday today
    td = date.today()
    birthday_clients = Client.objects.filter(birth_date__day=td.day, birth_date__month=td.month)
    birthday_today = birthday_clients.count()

    # Payments journal (last 200)
    payments_journal = (
        Payment.objects.select_related('rental__client').order_by('-created_at')[:200]
    )

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
    recalculate_inventory_counters()

    fmt = request.GET.get('format', 'csv')
    report = request.GET.get('report', 'payments')

    if report == 'inventory':
        headers = ['Категория', 'Наименование', 'Размер', 'Статус', 'Всего',
                   'В аренде', 'Доступно', 'Загрузка %', 'Цена/день']
        rows = []
        for eq in Equipment.objects.select_related('type').prefetch_related('sizes').order_by('type__name', 'name'):
            sizes = list(eq.sizes.all())
            if sizes:
                for sz in sizes:
                    avail = sz.quantity - sz.quantity_rented
                    load = round(sz.quantity_rented / sz.quantity * 100) if sz.quantity else 0
                    rows.append([
                        eq.type.name, eq.name, sz.size,
                        dict(Equipment.STATUS_CHOICES).get(eq.status, eq.status),
                        sz.quantity, sz.quantity_rented, avail, f'{load}%', str(eq.price_per_day),
                    ])
            else:
                avail = eq.quantity - eq.quantity_rented
                load = round(eq.quantity_rented / eq.quantity * 100) if eq.quantity else 0
                rows.append([
                    eq.type.name, eq.name, eq.size or '—',
                    dict(Equipment.STATUS_CHOICES).get(eq.status, eq.status),
                    eq.quantity, eq.quantity_rented, avail, f'{load}%', str(eq.price_per_day),
                ])
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
        headers = ['ID', 'Договор', 'Клиент', 'Начало', 'Конец', 'Статус', 'Сумма']
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
            rows.append([
                'Аренда', r.id, str(r.created_at.date()),
                r.client.full_name if r.client else '',
                r.contract_number, str(r.total_price), r.status,
            ])
        for p in Payment.objects.select_related('rental__client').order_by('-created_at'):
            rows.append([
                'Платёж', p.id, str(p.created_at.date()),
                p.rental.client.full_name if p.rental.client else '',
                p.payment_method, str(p.amount), p.status,
            ])

    if fmt == 'excel':
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Font, PatternFill
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = filename[:31]
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
            resp = HttpResponse(
                buf.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            resp['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            return resp
        except ImportError:
            pass

    # CSV fallback
    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(resp)
    writer.writerow(headers)
    writer.writerows(rows)
    return resp


# ═════════════════════════════════════════════════════════════════════════
#  AI ASSISTANT (Решид) — OpenRouter
# ═════════════════════════════════════════════════════════════════════════


# Системный промпт ассистента Решид
_SYSTEM_PROMPT = """Ты — Решид, ИИ-ассистент горнолыжного проката Ski Rent.
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
КАК СОЗДАТЬ АРЕНДУ
════════════════════════════════════════
1. Перейти: Аренды → «+ Новая аренда»
2. Выбрать клиента из списка (или сначала создать его в разделе «Клиенты»)
3. Выбрать начало аренды и количество дней
4. Добавить снаряжение: «+ Добавить позицию» → выбрать тип + размер + кол-во
5. При необходимости выбрать скидку
6. Нажать «Создать аренду»

════════════════════════════════════════
КАК ПОДПИСАТЬ ДОГОВОР
════════════════════════════════════════
1. В списке аренд нажать «Договор»
2. Откроется страница договора /contracts/<id>/
3. Способы подписания:
   — SMS OTP: 6-значный код, действует 120 секунд
   — ЭЦП NCALayer: через карт-ридер (программа NCALayer должна быть запущена)
4. После подписания PDF договора отправляется на email клиента

════════════════════════════════════════
КАК ПРИНЯТЬ ПЛАТЁЖ
════════════════════════════════════════
Путь: Платежи → «+ Новый платёж»
Поля: выбрать аренду → метод оплаты → сумма
Методы: Kaspi Bank, Halyk Bank, Наличные
Статусы: paid, partially_refunded, refunded
Возвраты — только manager и admin (Платежи → «Возврат»).

════════════════════════════════════════
КЛИЕНТЫ И СНАРЯЖЕНИЕ
════════════════════════════════════════
Клиент: ФИО, телефон (обяз.), email, ИИН, документ, дата рождения.
Снаряжение: тип, название, размер, цена/день, количество.
Статусы снаряжения: available, rented, repair.
Ведомость остатков — /warehouse/.

════════════════════════════════════════
АНАЛИТИКА (admin / manager)
════════════════════════════════════════
/analytics/ — выручка, аренды по месяцам, статусы, методы оплаты, топ снаряжения.
Экспорт в Excel/CSV: платежи, аренды, ведомость, полный отчёт.

════════════════════════════════════════
НАСТРОЙКИ (только admin)
════════════════════════════════════════
/settings/ — сохранить/проверить ключ Groq API для ИИ-ассистента.
Ключ хранится в AppSettings (ключ GROQ_API_KEY).

════════════════════════════════════════
ЧАСТЫЕ ПРОБЛЕМЫ
════════════════════════════════════════
• «Снаряжение недоступно» — проверьте quantity_available на странице Склад
• «Договор уже существует» — нажмите «Договор» для просмотра
• «SMS не приходит» — проверьте SMSC_LOGIN/SMSC_PASSWORD в .env; код действует 120 секунд
• «PDF не генерируется» — нужна библиотека reportlab (pip install reportlab)
• ИИ не отвечает — перейдите в /settings/ и проверьте GROQ_API_KEY

Если вопрос не относится к работе Ski Rent CRM, вежливо объясни что ты специализируешься на этой системе."""


def _resolve_openrouter_key():
    """Приоритет: БД → settings.py → переменная окружения."""
    import os
    key = (
        AppSettings.get('OPENROUTER_API_KEY')
        or getattr(dj_settings, 'OPENROUTER_API_KEY', '')
        or os.environ.get('OPENROUTER_API_KEY', '')
    ).strip()
    return key




@login_required(login_url='login')
@require_POST
def ai_chat_view(request):
    """ИИ-ассистент Решид (Groq Cloud API, OpenAI-совместимый формат)."""
    try:
        body = _json.loads(request.body)
        user_message = body.get('message', '').strip()
        history = body.get('history', [])
        if not user_message:
            return JsonResponse({'reply': 'Пожалуйста, введите сообщение.'})

        api_key = _resolve_openrouter_key()

        if not api_key:
            return JsonResponse({
                'reply': '⚠️ API-ключ OpenRouter не настроен.\n'
                         'Перейдите в **Настройки → ИИ-ассистент** и введите ключ.\n'
                         'Получить ключ: https://openrouter.ai/',
                'no_key': True,
            })

        # OpenRouter format (OpenAI-compatible)
        messages_payload = [{'role': 'system', 'content': _SYSTEM_PROMPT}]
        for h in history[-8:]:
            if h.get('role') in ('user', 'assistant') and h.get('content', '').strip():
                messages_payload.append({
                    'role': h['role'],
                    'content': str(h['content'])[:1000],
                })
        messages_payload.append({'role': 'user', 'content': user_message})

        # OpenRouter format (OpenAI-compatible)
        openrouter_messages = []

        for msg in messages_payload:
            role = msg['role']
            if role == 'system':
                role = 'system'
            elif role == 'assistant':
                role = 'assistant'
            else:
                role = 'user'

            openrouter_messages.append({
                'role': role,
                'content': msg['content'],
            })

        last_error = None
        reply = None

        for model in OPENROUTER_MODELS:
            try:
                req_data = _json.dumps({
                    'model': model,
                    'messages': openrouter_messages,
                    'temperature': 0.5,
                    'max_tokens': 500,
                }).encode('utf-8')

                req = urllib.request.Request(
                    'https://openrouter.ai/api/v1/chat/completions',
                    data=req_data,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {api_key}',
                        'HTTP-Referer': 'https://localhost',
                        'X-Title': 'Ski Rent CRM',
                    },
                    method='POST',
                )

                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = _json.loads(resp.read().decode('utf-8'))

                choices = result.get('choices', [])
                if choices:
                    reply = choices[0].get('message', {}).get('content', '').strip()
                    break

            except urllib.error.HTTPError as e:
                last_error = e
                continue

        if not reply:
            raise last_error

        return JsonResponse({'reply': reply})

    except urllib.error.HTTPError as e:
        code = e.code
        try:
            err_body = _json.loads(e.read().decode('utf-8', errors='replace'))
            err_detail = err_body.get('error', {}).get('message', '')
        except Exception:
            err_detail = ''
        if code == 401:
            return JsonResponse({
                'reply': '❌ Неверный API-ключ OpenRouter (ошибка 401).\n'
                         'Перейдите в /settings/ и введите корректный ключ.',
                'no_key': True,
            })
        elif code == 429:
            return JsonResponse({
                'reply': '⏳ Превышен лимит запросов OpenRouter API. Попробуйте позже.',
            })
        elif code == 403:
            return JsonResponse({
                'reply': '❌ OpenRouter API временно недоступен или превышен лимит.',
            })
        else:
            extra = f' — {err_detail}' if err_detail else ''
            logger.exception('OpenRouter API error %s: %s', code, err_detail)
            return JsonResponse({
                'reply': f'Ошибка OpenRouter API: {code}{extra}. Проверьте ключ.',
            })
    except Exception as exc:
        return JsonResponse(
            {'reply': f'Ошибка соединения: {exc}. Проверьте доступ к интернету.'},
            status=200,
        )


# ═════════════════════════════════════════════════════════════════════════
#  APP SETTINGS (API ключи и т.п.)
# ═════════════════════════════════════════════════════════════════════════

@login_required(login_url='login')
def app_settings_view(request):
    """Страница настроек приложения — только для admin."""
    if request.user.role != 'admin':
        return redirect('dashboard')

    msg_ok = msg_err = None

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'save_openrouter_key':
            key = request.POST.get('openrouter_key', '').strip()
            if key:
                AppSettings.set(
                    'OPENROUTER_API_KEY', key,
                    note='Ключ OpenRouter API для ИИ-ассистента Решид',
                )
                msg_ok = 'API-ключ OpenRouter сохранён. ИИ-ассистент готов к работе!'
            else:
                AppSettings.set('OPENROUTER_API_KEY', '')
                msg_ok = 'API-ключ очищен.'

        elif action == 'test_openrouter_key':
            api_key = _resolve_openrouter_key()

            if not api_key:
                msg_err = 'API-ключ OpenRouter не задан.'
            else:
                try:
                    req_data = _json.dumps({
                        'model': 'mistralai/mistral-7b-instruct:free',
                        'messages': [{'role': 'user', 'content': 'ping'}],
                    }).encode('utf-8')

                    req = urllib.request.Request(
                        'https://openrouter.ai/api/v1/chat/completions',
                        data=req_data,
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {api_key}',
                            'HTTP-Referer': 'https://localhost',
                            'X-Title': 'Ski Rent CRM',
                        },
                        method='POST',
                    )

                    with urllib.request.urlopen(req, timeout=15) as resp:
                        _json.loads(resp.read())

                    msg_ok = '✅ Подключение к OpenRouter API успешно! ИИ-ассистент работает.'

                except urllib.error.HTTPError as e:
                    try:
                        err_body = _json.loads(e.read().decode('utf-8', errors='replace'))
                        err_detail = err_body.get('error', {}).get('message', str(err_body))
                    except Exception:
                        err_detail = '(не удалось прочитать ответ)'

                    msg_err = f'❌ Ошибка {e.code}: {err_detail}'

                except Exception as ex:
                    msg_err = f'❌ Ошибка соединения: {ex}'

    # Текущий сохранённый ключ — маскируем
    stored_key = AppSettings.get('OPENROUTER_API_KEY', '')
    masked_key = ''
    if stored_key:
        if len(stored_key) > 16:
            masked_key = stored_key[:8] + '•' * (len(stored_key) - 12) + stored_key[-4:]
        else:
            masked_key = '•' * len(stored_key)

    context = {
        'user': request.user,
        'role': request.user.role,
        'is_admin': True,
        'is_manager': True,
        'is_cashier': True,
        'msg_ok': msg_ok,
        'msg_err': msg_err,
        'has_openrouter_key': bool(stored_key),
        'masked_key': masked_key,
    }
    return render(request, 'app_settings.html', context)
