import re
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """Нормализует телефон к формату +7XXXXXXXXXX."""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    if digits.startswith('7') and len(digits) == 11:
        return '+' + digits
    if len(digits) == 10:
        return '+7' + digits
    return '+' + digits if digits else phone


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

    # ── Попытка реальной отправки через smsc.kz ──────────────────────────────
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

    # ── Нет учётных данных ───────────────────────────────────────────────────
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

    # Список снаряжения из аренды
    items = rental.items.select_related('equipment').all()
    if items.exists():
        parts = []
        for item in items:
            name = items.equipment.name
            size_str = f' p.{item.size}' if item.size else ''
            qty_str = f' x{item.quantity}' if item.quantity > 1 else ''
            parts.append(f'{name}{size_str}{qty_str} x{item.days}дн.')
        equipment_lines = ', '.join(parts)
    else:
        equipment_lines = 'снаряжение'

    # Форматируем даты
    start = rental.start_date.strftime('%d.%m.%Y') if rental.start_date else '—'
    end   = rental.end_date.strftime('%d.%m.%Y')   if rental.end_date   else '—'

    # Форматируем сумму
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
