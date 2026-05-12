"""Утилиты, переиспользуемые в rentals и других приложениях."""
import logging
import re

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone


logger = logging.getLogger(__name__)


ACTIVE_RENTAL_STATUSES = ("open", "booked", "rented")


# ─────────────────────────────────────────
#  Phone normalization
# ─────────────────────────────────────────
def normalize_phone(phone: str) -> str:
    """Нормализует телефон к формату +7XXXXXXXXXX."""
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    if digits.startswith('7') and len(digits) == 11:
        return '+' + digits
    if len(digits) == 10:
        return '+7' + digits
    return '+' + digits if digits else phone


# ─────────────────────────────────────────
#  SMS (smsc.kz)
# ─────────────────────────────────────────
def send_sms(phone: str, message: str):
    """
    Отправляет SMS через smsc.kz.

    В DEBUG-режиме (или при неверных учётных данных) логирует в консоль
    и возвращает (True, None) — разработка не блокируется.

    Возвращает: (ok: bool, error: str | None)
    """
    login    = (getattr(settings, 'SMSC_LOGIN',    '') or '').strip()
    password = (getattr(settings, 'SMSC_PASSWORD', '') or '').strip()

    strict_real_send = bool(getattr(settings, "SMS_STRICT_REAL_SEND", True))

    # ── Попытка реальной отправки через smsc.kz ─────────────────────────
    if login and password:
        try:
            import requests as _req

            url    = getattr(settings, 'SMS_API_URL', 'https://smsc.kz/sys/send.php')
            sender = getattr(settings, 'SMS_SENDER',  'SkiRent')
            params = {
                'login':   login,
                'psw':     password,
                'phones':  phone,
                'mes':     message,
                'sender':  sender,
                'fmt':     3,           # JSON-ответ
                'charset': 'utf-8',
            }
            resp = _req.get(url, params=params, timeout=15)
            data = resp.json()

            if 'error' in data:
                code = str(data.get('error_code', '')).strip()
                err = (code + ' ' + str(data['error'])).strip()
                if code == '2':
                    err += ' (проверьте SMSC_LOGIN/SMSC_PASSWORD)'
                elif code == '4':
                    err += ' (IP заблокирован в SMSC, разблокируйте/добавьте IP в кабинете)'
                logger.warning('smsc.kz error: %s', err)
                if getattr(settings, 'DEBUG', False) and not strict_real_send:
                    logger.warning('[SMS-CONSOLE] %s -> %s', phone, message)
                    return True, None
                return False, err

            logger.info('SMS отправлена на %s (id=%s)', phone, data.get('id'))
            return True, None

        except Exception as exc:
            logger.warning('send_sms exception: %s', exc)
            if getattr(settings, 'DEBUG', False) and not strict_real_send:
                logger.warning('[SMS-CONSOLE] %s -> %s', phone, message)
                return True, None
            return False, str(exc)

    # ── Нет учётных данных ─────────────────────────────────────────────
    if getattr(settings, 'DEBUG', False) and not strict_real_send:
        logger.warning('[SMS-CONSOLE] %s -> %s', phone, message)
        return True, None

    return False, 'smsc_not_configured'


def build_contract_sms(contract) -> str:
    """
    Формирует текст SMS-копии договора, который уходит клиенту.

    SMS-провайдер автоматически разобьёт длинный текст на части.
    """
    client = contract.client
    rental = contract.rental

    items = rental.items.select_related('equipment').all()
    if items.exists():
        equipment_lines = ', '.join(
            f'{item.equipment.name} x{item.days}дн.'
            for item in items
        )
    else:
        equipment_lines = 'снаряжение'

    start = rental.start_date.strftime('%d.%m.%Y') if rental.start_date else '—'
    end   = rental.end_date.strftime('%d.%m.%Y')   if rental.end_date   else '—'

    price = f'{rental.total_price:,.0f} ₸'.replace(',', ' ') if rental.total_price else '—'

    text = (
        f'ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ #{contract.id}\n'
        f'SkiRent\n'
        f'\n'
        f'Клиент: {client.full_name}\n'
        f'Телефон: {client.phone}\n'
        f'\n'
        f'Снаряжение: {equipment_lines}\n'
        f'Срок аренды: {start} — {end}\n'
        f'Сумма: {price}\n'
        f'\n'
        f'Условия:\n'
        f'1. Вернуть оборудование в срок.\n'
        f'2. При повреждении — компенсация.\n'
        f'3. Оплата производится заранее.\n'
        f'\n'
        f'Подтверждая договор, вы соглашаетесь со всеми условиями.\n'
        f'Номер договора: #{contract.id}'
    )
    return text


# ─────────────────────────────────────────
#  Rental / inventory housekeeping
# ─────────────────────────────────────────
def close_expired_rentals():
    """Переводит просроченные аренды в статус 'completed'."""
    from .models import Rental
    today = timezone.localdate()
    Rental.objects.filter(
        status__in=ACTIVE_RENTAL_STATUSES,
        end_date__lt=today,
    ).update(status="completed")


def recalculate_inventory_counters():
    """Пересчитывает поля quantity_rented по активным арендам."""
    from equipment.models import Equipment, EquipmentSize
    from .models import RentalItem

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
        .exclude(equipment_size__isnull=True)
        .values("equipment_size_id")
        .annotate(total=Sum("quantity"))
    )

    for row in rented_by_size:
        EquipmentSize.objects.filter(
            pk=row["equipment_size_id"]
        ).update(quantity_rented=row["total"] or 0)
