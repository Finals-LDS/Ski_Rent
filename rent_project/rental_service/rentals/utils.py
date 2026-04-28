import io
import re
import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def generate_contract_pdf(contract) -> bytes:
    """Генерирует PDF договора и возвращает байты."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas as pdf_canvas
    except ImportError:
        logger.warning('reportlab не установлен — PDF не сформирован')
        return b''

    client = contract.client
    rental = contract.rental
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Заголовок
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(width / 2, height - 2 * cm, 'ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ')
    c.setFont('Helvetica', 11)
    c.drawCentredString(width / 2, height - 2.8 * cm, f'Договор #{contract.id}   |   {contract.created_at.strftime("%d.%m.%Y")}')

    y = height - 4 * cm
    left = 2 * cm

    def line(text, bold=False, offset=0.6):
        nonlocal y
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', 11)
        c.drawString(left, y, text)
        y -= offset * cm

    line('Стороны договора:', bold=True)
    line(f'Клиент: {client.full_name}')
    line(f'Телефон: {client.phone or "—"}')
    line(f'Email:   {client.email or "—"}')
    y -= 0.3 * cm

    line('Снаряжение:', bold=True)
    items = rental.items.select_related('equipment').all()
    for item in items:
        size_str = f', р. {item.size}' if item.size else ''
        qty_str = f' x{item.quantity}' if item.quantity > 1 else ''
        price_total = item.price_per_day * item.days * item.quantity
        line(
            f'  {item.equipment.name}{size_str}{qty_str}'
            f'  —  {item.days} дн. x {item.price_per_day} = {price_total} ₸'
        )
    y -= 0.3 * cm

    line('Срок аренды:', bold=True)
    line(f'  С {rental.start_date or "—"} по {rental.end_date or "—"}')
    y -= 0.3 * cm

    line('Итого:', bold=True)
    line(f'  {rental.total_price} ₸')
    if rental.discount:
        line(f'  Скидка: {rental.discount.name} ({rental.discount.percent}%)')
    y -= 0.3 * cm

    line('Условия договора:', bold=True)
    for cond in [
        '1. Клиент обязуется вернуть снаряжение в срок.',
        '2. В случае повреждения — компенсация по рыночной стоимости.',
        '3. Оплата производится в момент получения снаряжения.',
        '4. Подписывая договор, клиент подтверждает ознакомление с условиями.',
    ]:
        line(cond)
    y -= 0.3 * cm

    signed_at = contract.accepted_at
    sign_str = signed_at.strftime('%d.%m.%Y %H:%M') if signed_at else '—'
    line(f'Статус: Подписан  |  Дата подписания: {sign_str}', bold=True)

    c.save()
    buf.seek(0)
    return buf.read()


def send_contract_pdf_email(contract):
    """Отправляет PDF договора клиенту на email."""
    email = contract.client.email
    if not email:
        return

    pdf_bytes = generate_contract_pdf(contract)
    if not pdf_bytes:
        return

    subject = f'Ski Rent — Договор аренды #{contract.id} (подписан)'
    body = (
        f'Уважаемый(ая) {contract.client.full_name},\n\n'
        f'Договор аренды снаряжения #{contract.id} успешно подписан.\n'
        f'Копия договора прикреплена к этому письму в формате PDF.\n\n'
        f'Если у вас возникли вопросы, свяжитесь с нами.\n\n'
        f'С уважением,\nКоманда Ski Rent'
    )

    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@skirent.kz'),
            to=[email],
        )
        msg.attach(f'contract_{contract.id}.pdf', pdf_bytes, 'application/pdf')
        msg.send(fail_silently=True)
    except Exception as exc:
        logger.warning('Не удалось отправить PDF договора на %s: %s', email, exc)


def send_contract_copy_email(contract, otp_code: str):
    """Отправляет копию договора + OTP на email клиента."""
    email = contract.client.email
    if not email:
        return

    client = contract.client
    rental = contract.rental
    items = rental.items.select_related('equipment').all()
    lines = []
    for item in items:
        size_str = f', р. {item.size}' if item.size else ''
        qty_str = f' x{item.quantity}' if item.quantity > 1 else ''
        price_total = item.price_per_day * item.days * item.quantity
        lines.append(
            f'  • {item.equipment.name}{size_str}{qty_str}'
            f'  — {item.days} дн. × {item.price_per_day} ₸ = {price_total} ₸'
        )
    equipment_block = '\n'.join(lines) if lines else '  — снаряжение не указано'

    start = rental.start_date.strftime('%d.%m.%Y') if rental.start_date else '—'
    end = rental.end_date.strftime('%d.%m.%Y') if rental.end_date else '—'

    subject = f'Ski Rent — Договор аренды #{contract.id}'
    body = (
        f'Уважаемый(ая) {client.full_name},\n\n'
        f'Ниже приведены условия договора аренды снаряжения:\n\n'
        f'Договор №: {contract.id}\n'
        f'Снаряжение:\n{equipment_block}\n\n'
        f'Срок аренды: {start} — {end}\n'
        f'Итого: {rental.total_price} ₸\n\n'
        f'Условия:\n'
        f'1. Вернуть снаряжение в срок.\n'
        f'2. При повреждении — компенсация.\n'
        f'3. Оплата производится заранее.\n\n'
        f'━━━━━━━━━━━━━━━━━━━━━━\n'
        f'КОД ПОДПИСАНИЯ ДОГОВОРА: {otp_code}\n'
        f'Сообщите этот код оператору для подтверждения.\n'
        f'Код действителен 2 минуты.\n'
        f'Никому не передавайте его, кроме оператора Ski Rent.\n'
        f'━━━━━━━━━━━━━━━━━━━━━━\n\n'
        f'С уважением,\nКоманда Ski Rent'
    )

    try:
        from django.core.mail import send_mail
        send_mail(
            subject, body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@skirent.kz'),
            [email],
            fail_silently=True,
        )
    except Exception as exc:
        logger.warning('Не удалось отправить копию договора на %s: %s', email, exc)


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
