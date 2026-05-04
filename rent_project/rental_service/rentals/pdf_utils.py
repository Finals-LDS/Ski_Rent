"""
Генерация PDF договора для клиента.
Используется reportlab. Установить: pip install reportlab
"""
import io
from datetime import date

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


def _register_fonts():
    """Регистрируем шрифт с поддержкой кириллицы."""
    # Пробуем DejaVu (обычно есть в Linux)
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('DejaVuSans', path))
                bold_path = path.replace('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_path))
                    return 'DejaVuSans', 'DejaVuSans-Bold'
                return 'DejaVuSans', 'DejaVuSans'
            except Exception:
                continue
    return 'Helvetica', 'Helvetica-Bold'


def generate_contract_pdf(contract) -> bytes:
    """
    Генерирует PDF договора и возвращает bytes.
    contract — экземпляр rentals.models.Contract.
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "reportlab не установлен. Выполните: pip install reportlab"
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    normal_font, bold_font = _register_fonts()

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        'ContractTitle',
        fontName=bold_font,
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    style_subtitle = ParagraphStyle(
        'ContractSubtitle',
        fontName=normal_font,
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#555555'),
        spaceAfter=14,
    )
    style_body = ParagraphStyle(
        'ContractBody',
        fontName=normal_font,
        fontSize=10,
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    style_label = ParagraphStyle(
        'ContractLabel',
        fontName=bold_font,
        fontSize=10,
        spaceAfter=4,
    )
    style_small = ParagraphStyle(
        'ContractSmall',
        fontName=normal_font,
        fontSize=9,
        textColor=colors.HexColor('#777777'),
        spaceAfter=4,
    )

    rental = contract.rental
    client = contract.client
    today_str = date.today().strftime('%d.%m.%Y')

    story = []

    # Заголовок
    story.append(Paragraph("ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ", style_title))
    story.append(Paragraph(
        f"№ {rental.contract_number} от {today_str} г.",
        style_subtitle,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CCCCCC')))
    story.append(Spacer(1, 14))

    # Стороны
    story.append(Paragraph("1. СТОРОНЫ ДОГОВОРА", style_label))
    story.append(Paragraph(
        f"<b>Арендодатель:</b> Ski Rent (далее — «Компания»)",
        style_body,
    ))
    story.append(Paragraph(
        f"<b>Арендатор:</b> {client.full_name} "
        f"(документ: {client.document_id or '—'}, "
        f"телефон: {client.phone or '—'}, "
        f"email: {client.email or '—'})",
        style_body,
    ))
    story.append(Spacer(1, 8))

    # Предмет договора
    story.append(Paragraph("2. ПРЕДМЕТ ДОГОВОРА", style_label))
    story.append(Paragraph(
        "Компания передаёт Арендатору во временное пользование горнолыжное снаряжение, "
        "указанное в перечне ниже, а Арендатор обязуется принять его, использовать по "
        "назначению и вернуть в исправном состоянии.",
        style_body,
    ))

    # Таблица снаряжения
    items_data = [['Снаряжение', 'Дней', 'Цена/день', 'Итого']]
    for item in rental.items.select_related('equipment').all():
        items_data.append([
            item.equipment.name,
            str(item.days),
            f"{item.price_per_day:,.0f} ₸",
            f"{item.get_total():,.0f} ₸",
        ])
    items_data.append(['', '', 'ИТОГО:', f"{rental.total_price:,.0f} ₸"])

    t = Table(items_data, colWidths=[9 * cm, 2 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), bold_font),
        ('FONTNAME', (0, 1), (-1, -1), normal_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F0F4FF')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#DDDDDD')),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#333333')),
        ('FONTNAME', (2, -1), (-1, -1), bold_font),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Период
    story.append(Paragraph("3. СРОК АРЕНДЫ", style_label))
    story.append(Paragraph(
        f"Начало: <b>{rental.start_date.strftime('%d.%m.%Y') if rental.start_date else '—'}</b> &nbsp;&nbsp; "
        f"Окончание: <b>{rental.end_date.strftime('%d.%m.%Y') if rental.end_date else '—'}</b>",
        style_body,
    ))
    story.append(Spacer(1, 8))

    # Условия
    story.append(Paragraph("4. УСЛОВИЯ АРЕНДЫ", style_label))
    conditions = [
        "Арендатор обязуется использовать снаряжение только по его прямому назначению.",
        "В случае повреждения или утраты снаряжения Арендатор возмещает его полную рыночную стоимость.",
        "Снаряжение возвращается в чистом виде в срок, указанный в п. 3.",
        "При задержке возврата снаряжения начисляется пени в размере 1% от стоимости аренды за каждый день просрочки.",
        "Компания не несёт ответственности за травмы, полученные при использовании снаряжения.",
        "Арендатор подтверждает своё ознакомление с настоящим договором и согласие с его условиями.",
    ]
    for i, cond in enumerate(conditions, 1):
        story.append(Paragraph(f"4.{i}. {cond}", style_body))
    story.append(Spacer(1, 12))

    # Подписи
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CCCCCC')))
    story.append(Spacer(1, 10))
    story.append(Paragraph("5. ПОДПИСИ СТОРОН", style_label))

    sig_data = [
        ['Арендодатель (Ski Rent)', '', 'Арендатор'],
        ['', '', ''],
        ['_______________________', '', '_______________________'],
        [f'Дата: {today_str}', '', f'Дата: {today_str}'],
    ]
    sig_table = Table(sig_data, colWidths=[7 * cm, 3 * cm, 7 * cm])
    sig_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), normal_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_table)

    # Статус подписания
    story.append(Spacer(1, 12))
    status_map = {
        'signed_sms': '✓ Подписан через SMS OTP',
        'signed_card': '✓ Подписан через ЭЦП',
        'accepted': '✓ Принят',
        'draft': 'Черновик',
        'sent': 'Отправлен, ожидает подписи',
        'rejected': '✗ Отклонён',
    }
    status_text = status_map.get(contract.status, contract.status)
    if contract.accepted_at:
        status_text += f" — {contract.accepted_at.strftime('%d.%m.%Y %H:%M')}"
    story.append(Paragraph(
        f"<i>Статус договора: {status_text}</i>",
        style_small,
    ))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
