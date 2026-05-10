"""
Генерация PDF договора аренды снаряжения.
Использует reportlab. Установить: pip install reportlab

Текст договора и оформление вынесены в константы ниже,
чтобы его было удобно редактировать без правки кода.
"""
import io
import os
from datetime import date

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ═════════════════════════════════════════════════════════════════════════
#  СОДЕРЖАНИЕ ДОГОВОРА — все тексты в одном месте, легко править
# ═════════════════════════════════════════════════════════════════════════

COMPANY_NAME = 'Ski Rent'
COMPANY_NAME_FULL = 'Ski Rent (далее — «Компания»)'
COMPANY_LOCATION = 'Алматы'

CONTRACT_TITLE = 'ДОГОВОР АРЕНДЫ СНАРЯЖЕНИЯ'

# Названия разделов договора
SECTION_PARTIES   = '1. СТОРОНЫ ДОГОВОРА'
SECTION_SUBJECT   = '2. ПРЕДМЕТ ДОГОВОРА'
SECTION_PERIOD    = '3. СРОК АРЕНДЫ'
SECTION_TERMS     = '4. УСЛОВИЯ АРЕНДЫ'
SECTION_SIGNS     = '5. ПОДПИСИ СТОРОН'

# Подписи к строкам
LABEL_LANDLORD = 'Арендодатель'
LABEL_TENANT   = 'Арендатор'
LABEL_TOTAL    = 'ИТОГО:'
LABEL_DATE     = 'Дата'

# Заголовки колонок таблицы снаряжения
TABLE_HEADERS = ['Снаряжение', 'Дней', 'Цена/день', 'Итого']

# Текст пункта о предмете договора
SUBJECT_TEXT = (
    'Компания передаёт Арендатору во временное пользование горнолыжное снаряжение, '
    'указанное в перечне ниже, а Арендатор обязуется принять его, использовать по '
    'назначению и вернуть в исправном состоянии.'
)

# Условия аренды (нумеруются автоматически 4.1, 4.2, ...)
CONTRACT_CONDITIONS = [
    'Арендатор обязуется использовать снаряжение только по его прямому назначению.',
    'В случае повреждения или утраты снаряжения Арендатор возмещает его полную рыночную стоимость.',
    'Снаряжение возвращается в чистом виде в срок, указанный в п. 3.',
    'При задержке возврата снаряжения начисляется пени в размере 1% от стоимости '
    'аренды за каждый день просрочки.',
    'Компания не несёт ответственности за травмы, полученные при использовании снаряжения.',
    'Арендатор подтверждает своё ознакомление с настоящим договором и согласие с его условиями.',
]

# Человекочитаемые названия статусов договора
STATUS_TEXT_MAP = {
    'signed_sms':  '✓ Подписан через SMS OTP',
    'signed_card': '✓ Подписан через ЭЦП',
    'accepted':    '✓ Принят',
    'draft':       'Черновик',
    'sent':        'Отправлен, ожидает подписи',
    'rejected':    '✗ Отклонён',
}

# Шрифт с поддержкой кириллицы
FONT_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
]

# Размеры/отступы документа (см)
PAGE_MARGIN_CM = 2

# Цвета оформления
COLOR_TABLE_HEAD_BG = '#F0F4FF'
COLOR_TABLE_GRID    = '#DDDDDD'
COLOR_TABLE_TOTAL   = '#333333'
COLOR_HR            = '#CCCCCC'
COLOR_SUBTITLE      = '#555555'
COLOR_SMALL_TEXT    = '#777777'


# ═════════════════════════════════════════════════════════════════════════
#  Регистрация шрифта (один раз)
# ═════════════════════════════════════════════════════════════════════════

def _register_fonts():
    """Регистрирует шрифт с поддержкой кириллицы. Возвращает (normal, bold)."""
    for path in FONT_PATHS:
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


# ═════════════════════════════════════════════════════════════════════════
#  Стили абзацев
# ═════════════════════════════════════════════════════════════════════════

def _build_styles(normal_font, bold_font):
    return {
        'title': ParagraphStyle(
            'ContractTitle', fontName=bold_font, fontSize=14,
            alignment=TA_CENTER, spaceAfter=6,
        ),
        'subtitle': ParagraphStyle(
            'ContractSubtitle', fontName=normal_font, fontSize=10,
            alignment=TA_CENTER, textColor=colors.HexColor(COLOR_SUBTITLE),
            spaceAfter=14,
        ),
        'body': ParagraphStyle(
            'ContractBody', fontName=normal_font, fontSize=10,
            leading=16, alignment=TA_JUSTIFY, spaceAfter=8,
        ),
        'label': ParagraphStyle(
            'ContractLabel', fontName=bold_font, fontSize=10, spaceAfter=4,
        ),
        'small': ParagraphStyle(
            'ContractSmall', fontName=normal_font, fontSize=9,
            textColor=colors.HexColor(COLOR_SMALL_TEXT), spaceAfter=4,
        ),
    }


# ═════════════════════════════════════════════════════════════════════════
#  Сборка частей договора
# ═════════════════════════════════════════════════════════════════════════

def _build_header(styles, rental, today_str):
    """Заголовок договора + номер."""
    return [
        Paragraph(CONTRACT_TITLE, styles['title']),
        Paragraph(f'№ {rental.contract_number} от {today_str} г.', styles['subtitle']),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor(COLOR_HR)),
        Spacer(1, 14),
    ]


def _build_parties(styles, client):
    """Раздел 'Стороны договора'."""
    return [
        Paragraph(SECTION_PARTIES, styles['label']),
        Paragraph(f'<b>{LABEL_LANDLORD}:</b> {COMPANY_NAME_FULL}', styles['body']),
        Paragraph(
            f'<b>{LABEL_TENANT}:</b> {client.full_name} '
            f'(документ: {client.document_id or "—"}, '
            f'телефон: {client.phone or "—"}, '
            f'email: {client.email or "—"})',
            styles['body'],
        ),
        Spacer(1, 8),
    ]


def _build_subject(styles):
    """Раздел 'Предмет договора'."""
    return [
        Paragraph(SECTION_SUBJECT, styles['label']),
        Paragraph(SUBJECT_TEXT, styles['body']),
    ]


def _build_items_table(rental, normal_font, bold_font):
    """Таблица снаряжения + итог."""
    data = [TABLE_HEADERS]
    for item in rental.items.select_related('equipment').all():
        data.append([
            item.equipment.name,
            str(item.days),
            f'{item.price_per_day:,.0f} ₸',
            f'{item.get_total():,.0f} ₸',
        ])
    data.append(['', '', LABEL_TOTAL, f'{rental.total_price:,.0f} ₸'])

    t = Table(data, colWidths=[9 * cm, 2 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), bold_font),
        ('FONTNAME', (0, 1), (-1, -1), normal_font),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(COLOR_TABLE_HEAD_BG)),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor(COLOR_TABLE_GRID)),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor(COLOR_TABLE_TOTAL)),
        ('FONTNAME', (2, -1), (-1, -1), bold_font),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return t


def _build_period(styles, rental):
    """Раздел 'Срок аренды'."""
    start = rental.start_date.strftime('%d.%m.%Y') if rental.start_date else '—'
    end   = rental.end_date.strftime('%d.%m.%Y')   if rental.end_date   else '—'
    return [
        Paragraph(SECTION_PERIOD, styles['label']),
        Paragraph(
            f'Начало: <b>{start}</b> &nbsp;&nbsp; Окончание: <b>{end}</b>',
            styles['body'],
        ),
        Spacer(1, 8),
    ]


def _build_conditions(styles):
    """Раздел 'Условия аренды'."""
    flow = [Paragraph(SECTION_TERMS, styles['label'])]
    for i, cond in enumerate(CONTRACT_CONDITIONS, 1):
        flow.append(Paragraph(f'4.{i}. {cond}', styles['body']))
    flow.append(Spacer(1, 12))
    return flow


def _build_signatures(styles, today_str, normal_font):
    """Раздел 'Подписи сторон'."""
    flow = [
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor(COLOR_HR)),
        Spacer(1, 10),
        Paragraph(SECTION_SIGNS, styles['label']),
    ]

    sig_data = [
        [f'{LABEL_LANDLORD} ({COMPANY_NAME})', '', LABEL_TENANT],
        ['', '', ''],
        ['_______________________', '', '_______________________'],
        [f'{LABEL_DATE}: {today_str}', '', f'{LABEL_DATE}: {today_str}'],
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
    flow.append(sig_table)
    return flow


def _build_status_line(styles, contract):
    """Подпись внизу: статус договора."""
    status_text = STATUS_TEXT_MAP.get(contract.status, contract.status)
    if contract.accepted_at:
        status_text += f' — {contract.accepted_at.strftime("%d.%m.%Y %H:%M")}'
    return [
        Spacer(1, 12),
        Paragraph(f'<i>Статус договора: {status_text}</i>', styles['small']),
    ]


# ═════════════════════════════════════════════════════════════════════════
#  Точка входа
# ═════════════════════════════════════════════════════════════════════════

def generate_contract_pdf(contract) -> bytes:
    """
    Собирает PDF договора и возвращает bytes.
    contract — экземпляр rentals.models.Contract.
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError(
            'reportlab не установлен. Выполните: pip install reportlab'
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_MARGIN_CM * cm, rightMargin=PAGE_MARGIN_CM * cm,
        topMargin=PAGE_MARGIN_CM * cm, bottomMargin=PAGE_MARGIN_CM * cm,
    )

    normal_font, bold_font = _register_fonts()
    styles = _build_styles(normal_font, bold_font)

    rental = contract.rental
    client = contract.client
    today_str = date.today().strftime('%d.%m.%Y')

    story = []
    story += _build_header(styles, rental, today_str)
    story += _build_parties(styles, client)
    story += _build_subject(styles)
    story.append(_build_items_table(rental, normal_font, bold_font))
    story.append(Spacer(1, 12))
    story += _build_period(styles, rental)
    story += _build_conditions(styles)
    story += _build_signatures(styles, today_str, normal_font)
    story += _build_status_line(styles, contract)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
