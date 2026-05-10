"""Бизнес-логика для аренд и договоров."""
import logging

from .models import Contract


logger = logging.getLogger(__name__)


def generate_contract_text(client, rental):
    """Текст договора (используется для коротких SMS / превью)."""
    items = rental.items.select_related('equipment').all()
    if items.exists():
        lines = []
        for item in items:
            name = item.equipment.name
            size_str = f', размер: {item.size}' if item.size else ''
            qty_str = f', кол-во: {item.quantity}' if item.quantity > 1 else ''
            price_total = item.price_per_day * item.days * item.quantity
            lines.append(
                f'  - {name}{size_str}{qty_str}, '
                f'{item.days} дн. × {item.price_per_day} ₸ = {price_total} ₸'
            )
        equipment_block = '\n'.join(lines)
    else:
        equipment_block = '     - снаряжение не указано'

    return f"""
    ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ

    Клиент: {client.full_name}
    Телефон: {client.phone}
    Снаряжение: {equipment_block}

    Срок аренды: {rental.start_date} - {rental.end_date}
    Итоговая стоимость: {rental.total_price} ₸

    Условия:
    1. Клиент обязуется вернуть оборудование в срок.
    2. В случае повреждения - компенсация.
    3. Оплата производится заранее.

    Подтверждая договор, вы соглашаетесь со всеми условиями.
    """


def can_start_rental(rental):
    """Можно ли начинать аренду — договор должен быть подписан."""
    try:
        contract = rental.contract
        return contract.is_signed
    except Contract.DoesNotExist:
        return False


def send_contract_pdf_email(contract):
    """Отправить PDF договора на email клиента. Безопасно при ошибках."""
    try:
        from django.conf import settings
        from django.core.mail import EmailMultiAlternatives

        from .pdf_utils import generate_contract_pdf

        if not contract.client.email:
            return False

        pdf_bytes = generate_contract_pdf(contract)
        subject = f'Договор аренды № {contract.rental.contract_number} — Ski Rent'
        body = (
            f'Уважаемый(ая) {contract.client.full_name},\n\n'
            f'Ваш договор аренды № {contract.rental.contract_number} подписан.\n'
            f'PDF-копия договора прикреплена к этому письму.\n\n'
            f'С уважением,\nКоманда Ski Rent'
        )
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[contract.client.email],
        )
        msg.attach(
            f'contract_{contract.rental.contract_number}.pdf',
            pdf_bytes, 'application/pdf',
        )
        msg.send(fail_silently=True)
        return True
    except Exception as exc:
        logger.warning('send_contract_pdf_email failed: %s', exc)
        return False
