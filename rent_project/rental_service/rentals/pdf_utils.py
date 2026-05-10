"""
Генерация PDF договора проката горнолыжного инвентаря.
Использует reportlab. Установить: pip install reportlab

Особенности:
- Шрифт DejaVuSans (с кириллицей) лежит в rentals/assets/fonts/ и едет
  вместе с кодом — никакого скачивания, гарантированно работает на App
  Engine. Положите DejaVuSans.ttf и DejaVuSans-Bold.ttf в эту папку.
- Текст договора, реквизиты Арендодателя и оформление вынесены в константы
  ниже — правьте без изменения кода.
- Поддержка вставки печати (см. STAMP_PATH ниже).
"""
import io
import logging
import os
from datetime import date
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate,
        Spacer, Table, TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
#  РЕКВИЗИТЫ АРЕНДОДАТЕЛЯ — заполните своими данными
# ═════════════════════════════════════════════════════════════════════════
LANDLORD_LEGAL_FORM = 'ИП'                       # ИП / ТОО
LANDLORD_NAME       = 'Ski Rent'
LANDLORD_CITY       = 'Алматы'
LANDLORD_ADDRESS    = 'г. Алматы, ул. ___________________'
LANDLORD_PHONE      = '+7 (___) ___-__-__'
LANDLORD_BIN_IIN    = '_____________'             # БИН/ИИН арендодателя

# Финансовые условия
DEPOSIT_AMOUNT_TEXT = 'согласно прайс-листу'      # либо «10 000»
LATE_RETURN_RATE    = 'согласно действующему тарифу'
RETURN_ADDRESS      = LANDLORD_ADDRESS             # адрес возврата

# Заголовок
CONTRACT_TITLE = 'ДОГОВОР ПРОКАТА ГОРНОЛЫЖНОГО ИНВЕНТАРЯ'


# ═════════════════════════════════════════════════════════════════════════
#  ПЕЧАТЬ (опционально)
# ═════════════════════════════════════════════════════════════════════════
# Положите PNG (лучше с прозрачным фоном) в rentals/assets/stamp.png
# Если файла нет — печать просто не отрисуется, без ошибок.
STAMP_PATH       = Path(__file__).parent / 'assets' / 'stamp.png'
STAMP_WIDTH_CM   = 3.5    # размер печати в PDF


# ═════════════════════════════════════════════════════════════════════════
#  ШРИФТ С ПОДДЕРЖКОЙ КИРИЛЛИЦЫ — лежит прямо в репо
# ═════════════════════════════════════════════════════════════════════════
# Шрифт хранится в rentals/assets/fonts/. Скачайте один раз
# (см. инструкцию в комментариях к проекту):
#   curl -L -o DejaVuSans.ttf \\
#     "https://cdn.jsdelivr.net/gh/dejavu-fonts/dejavu-fonts@version_2_37/ttf/DejaVuSans.ttf"
#   curl -L -o DejaVuSans-Bold.ttf \\
#     "https://cdn.jsdelivr.net/gh/dejavu-fonts/dejavu-fonts@version_2_37/ttf/DejaVuSans-Bold.ttf"
FONTS_DIR = Path(__file__).parent / 'assets' / 'fonts'


def _register_fonts():
    """
    Регистрирует кириллический шрифт. Возвращает (normal_name, bold_name).

    Сначала пробует DejaVu из репо (rentals/assets/fonts/), затем системные
    пути (Linux). Если ничего не нашлось — Helvetica + предупреждение в лог.
    """
    # Если уже зарегистрировано в этом процессе — не дублируем
    if 'DejaVuSans' in pdfmetrics.getRegisteredFontNames():
        return 'DejaVuSans', 'DejaVuSans-Bold'

    # 1. Шрифт из репо — самый надёжный способ
    bundled_regular = FONTS_DIR / 'DejaVuSans.ttf'
    bundled_bold    = FONTS_DIR / 'DejaVuSans-Bold.ttf'

    if bundled_regular.exists():
        try:
            pdfmetrics.registerFont(TTFont('DejaVuSans', str(bundled_regular)))
            if bundled_bold.exists():
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', str(bundled_bold)))
                logger.info('Loaded bundled DejaVu fonts from %s', FONTS_DIR)
                return 'DejaVuSans', 'DejaVuSans-Bold'
            logger.info('Loaded bundled DejaVuSans (no bold) from %s', FONTS_DIR)
            return 'DejaVuSans', 'DejaVuSans'
        except Exception as e:
            logger.warning('Failed to register bundled DejaVu font: %s', e)

    # 2. Системные пути (на Linux может стоять)
    for path in (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
    ):
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('DejaVuSans', path))
                bold_path = path.replace('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_path))
                    logger.info('Loaded system DejaVu fonts from %s', path)
                    return 'DejaVuSans', 'DejaVuSans-Bold'
                return 'DejaVuSans', 'DejaVuSans'
            except Exception as e:
                logger.warning('Failed to register system font %s: %s', path, e)
                continue

    # 3. Совсем грустный фоллбэк — кириллица будет видна как квадраты
    logger.error(
        'DejaVu font NOT FOUND. Looked in: %s and standard system paths. '
        'Cyrillic in PDF will appear as squares. '
        'Place DejaVuSans.ttf and DejaVuSans-Bold.ttf in %s.',
        FONTS_DIR, FONTS_DIR,
    )
    return 'Helvetica', 'Helvetica-Bold'


# ═════════════════════════════════════════════════════════════════════════
#  СТИЛИ
# ═════════════════════════════════════════════════════════════════════════

def _build_styles(normal_font, bold_font):
    return {
        'title': ParagraphStyle(
            'Title', fontName=bold_font, fontSize=13,
            alignment=TA_CENTER, spaceAfter=4, leading=16,
        ),
        'city_date': ParagraphStyle(
            'CityDate', fontName=normal_font, fontSize=10,
            alignment=TA_LEFT, spaceAfter=10,
        ),
        'preamble': ParagraphStyle(
            'Preamble', fontName=normal_font, fontSize=10,
            leading=14, alignment=TA_JUSTIFY, spaceAfter=10,
        ),
        'h2': ParagraphStyle(
            'H2', fontName=bold_font, fontSize=11,
            spaceBefore=8, spaceAfter=4,
        ),
        'body': ParagraphStyle(
            'Body', fontName=normal_font, fontSize=10,
            leading=14, alignment=TA_JUSTIFY, spaceAfter=4,
        ),
        'small': ParagraphStyle(
            'Small', fontName=normal_font, fontSize=9,
            textColor=colors.HexColor('#777777'), spaceAfter=4,
        ),
    }


# ═════════════════════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ═════════════════════════════════════════════════════════════════════════

def _format_date(d):
    """01.05.2026 → '«01» мая 2026 г.'."""
    if not d:
        return '«____» ______________ 20___ г.'
    months = [
        '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
    ]
    return f'«{d.day:02d}» {months[d.month]} {d.year} г.'


def _items_summary(rental):
    """Список позиций для п.1.1: 'Лыжи Atomic ×2 (р. 175); Ботинки ×1'."""
    items = rental.items.select_related('equipment').all()
    if not items.exists():
        return '____________________'
    parts = []
    for it in items:
        name = it.equipment.name
        qty = f' ×{it.quantity}' if it.quantity > 1 else ''
        size = f' (р. {it.size})' if it.size else ''
        parts.append(f'{name}{qty}{size}')
    return '; '.join(parts)


# ═════════════════════════════════════════════════════════════════════════
#  СБОРКА РАЗДЕЛОВ ДОГОВОРА
# ═════════════════════════════════════════════════════════════════════════

def _build_header(styles, sign_date_str):
    return [
        Paragraph(CONTRACT_TITLE, styles['title']),
        Paragraph(f'г. {LANDLORD_CITY}<br/>{sign_date_str}', styles['city_date']),
    ]


def _build_preamble(styles, client):
    return [
        Paragraph(
            f'{LANDLORD_LEGAL_FORM} <b>{LANDLORD_NAME}</b>, именуемый(ая) в дальнейшем '
            f'«Арендодатель», с одной стороны, и гражданин(ка) '
            f'<b>{client.full_name}</b>, ИИН {client.document_id or "____________________"}, '
            f'удостоверение личности № {client.document_id or "____________________"}, '
            f'именуемый(ая) в дальнейшем «Арендатор», с другой стороны, '
            f'заключили настоящий договор о нижеследующем.',
            styles['preamble'],
        ),
    ]


def _build_subject(styles, rental):
    flow = [Paragraph('1. Предмет договора', styles['h2'])]
    flow.append(Paragraph(
        '1.1. Арендодатель передаёт Арендатору во временное пользование '
        f'горнолыжный инвентарь: {_items_summary(rental)}.',
        styles['body'],
    ))
    flow.append(Paragraph(
        '1.2. Инвентарь передаётся в исправном состоянии, пригодном для эксплуатации.',
        styles['body'],
    ))
    start = _format_date(rental.start_date)
    end = _format_date(rental.end_date)
    flow.append(Paragraph(
        f'1.3. Срок аренды: с {start} по {end}.', styles['body'],
    ))
    return flow


def _build_payment(styles, rental):
    total = (
        f'{rental.total_price:,.0f}'.replace(',', ' ')
        if rental.total_price else '_________'
    )
    return [
        Paragraph('2. Стоимость аренды и порядок оплаты', styles['h2']),
        Paragraph(
            f'2.1. Стоимость аренды составляет <b>{total} тенге</b>.',
            styles['body'],
        ),
        Paragraph(
            '2.2. Арендатор обязуется оплатить стоимость аренды до получения инвентаря.',
            styles['body'],
        ),
        Paragraph(
            '2.3. По усмотрению Арендодателя может взиматься залог '
            f'в размере {DEPOSIT_AMOUNT_TEXT} либо документ, удостоверяющий личность.',
            styles['body'],
        ),
        Paragraph(
            '2.4. В случае просрочки возврата инвентаря Арендатор оплачивает '
            f'дополнительную аренду {LATE_RETURN_RATE}.',
            styles['body'],
        ),
    ]


def _build_rights(styles):
    return [
        Paragraph('3. Права и обязанности сторон', styles['h2']),
        Paragraph('<b>Арендодатель обязуется:</b>', styles['body']),
        Paragraph(
            '3.1. Передать исправный и подготовленный к эксплуатации инвентарь.',
            styles['body'],
        ),
        Paragraph(
            '3.2. Провести краткий инструктаж по использованию инвентаря.',
            styles['body'],
        ),
        Paragraph('<b>Арендатор обязуется:</b>', styles['body']),
        Paragraph('3.3. Использовать инвентарь только по назначению.', styles['body']),
        Paragraph(
            '3.4. Бережно относиться к инвентарю и соблюдать правила эксплуатации.',
            styles['body'],
        ),
        Paragraph('3.5. Не передавать инвентарь третьим лицам.', styles['body']),
        Paragraph(
            '3.6. Вернуть инвентарь в том же состоянии с учётом нормального износа.',
            styles['body'],
        ),
        Paragraph(
            '3.7. При повреждении, утере или краже инвентаря возместить причинённый ущерб.',
            styles['body'],
        ),
    ]


def _build_responsibility(styles):
    return [
        Paragraph('4. Ответственность сторон', styles['h2']),
        Paragraph(
            '4.1. Арендатор несёт полную материальную ответственность '
            'за переданный инвентарь на весь срок аренды.',
            styles['body'],
        ),
        Paragraph(
            '4.2. В случае поломки, утери или невозможности восстановления инвентаря '
            'Арендатор возмещает его полную стоимость согласно прайс-листу Арендодателя.',
            styles['body'],
        ),
        Paragraph(
            '4.3. Арендодатель не несёт ответственности за травмы, '
            'полученные Арендатором при использовании инвентаря.',
            styles['body'],
        ),
        Paragraph(
            '4.4. Арендатор подтверждает, что ознакомлен с правилами безопасности '
            'при катании на горных лыжах/сноуборде.',
            styles['body'],
        ),
    ]


def _build_return(styles):
    return [
        Paragraph('5. Возврат инвентаря', styles['h2']),
        Paragraph(
            f'5.1. Возврат осуществляется по адресу: {RETURN_ADDRESS}.',
            styles['body'],
        ),
        Paragraph('5.2. При возврате проводится осмотр инвентаря.', styles['body']),
        Paragraph(
            '5.3. При обнаружении повреждений составляется акт.',
            styles['body'],
        ),
    ]


def _build_final(styles):
    return [
        Paragraph('6. Заключительные положения', styles['h2']),
        Paragraph(
            '6.1. Подписывая настоящий договор, Арендатор подтверждает исправность '
            'полученного инвентаря и отсутствие претензий к его состоянию.',
            styles['body'],
        ),
        Paragraph(
            '6.2. Все споры решаются путём переговоров, а при невозможности '
            'достижения соглашения — в соответствии с законодательством '
            'Республики Казахстан.',
            styles['body'],
        ),
        Paragraph(
            '6.3. Настоящий договор вступает в силу с момента подписания сторонами.',
            styles['body'],
        ),
    ]


def _landlord_signature_cell(styles):
    """Подпись Арендодателя + печать (если файл с печатью есть)."""
    if STAMP_PATH.exists():
        try:
            img = Image(
                str(STAMP_PATH),
                width=STAMP_WIDTH_CM * cm,
                height=STAMP_WIDTH_CM * cm,
            )
            return KeepTogether([
                Paragraph('Подпись: _______________________', styles['body']),
                Spacer(1, 4),
                img,
            ])
        except Exception as e:
            logger.warning('Failed to load stamp image: %s', e)
    return Paragraph('Подпись: _______________________', styles['body'])


def _build_requisites(styles, client):
    flow = [Paragraph('Реквизиты и подписи сторон', styles['h2'])]

    data = [
        [
            Paragraph('<b>Арендодатель</b>', styles['body']),
            Paragraph('<b>Арендатор</b>', styles['body']),
        ],
        [
            Paragraph(
                f'{LANDLORD_LEGAL_FORM} {LANDLORD_NAME}<br/>'
                f'БИН/ИИН: {LANDLORD_BIN_IIN}<br/>'
                f'Адрес: {LANDLORD_ADDRESS}<br/>'
                f'Телефон: {LANDLORD_PHONE}',
                styles['body'],
            ),
            Paragraph(
                f'ФИО: {client.full_name}<br/>'
                f'ИИН: {client.document_id or "____________________"}<br/>'
                f'Телефон: {client.phone or "____________________"}<br/>'
                f'Email: {client.email or "—"}',
                styles['body'],
            ),
        ],
        [
            _landlord_signature_cell(styles),
            Paragraph('Подпись: _______________________', styles['body']),
        ],
    ]

    t = Table(data, colWidths=[8.5 * cm, 8.5 * cm])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    flow.append(t)
    return flow


def _build_status_line(styles, contract):
    status_map = {
        'signed_sms':  '✓ Подписан через SMS OTP',
        'signed_card': '✓ Подписан через ЭЦП',
        'accepted':    '✓ Принят',
        'draft':       'Черновик',
        'sent':        'Отправлен, ожидает подписи',
        'rejected':    '✗ Отклонён',
    }
    text = status_map.get(contract.status, contract.status)
    if contract.accepted_at:
        text += f' — {contract.accepted_at.strftime("%d.%m.%Y %H:%M")}'
    return [
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CCCCCC')),
        Spacer(1, 4),
        Paragraph(
            f'<i>Статус договора № {contract.rental.contract_number}: {text}</i>',
            styles['small'],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
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
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    normal_font, bold_font = _register_fonts()
    styles = _build_styles(normal_font, bold_font)

    rental = contract.rental
    client = contract.client
    sign_date = contract.accepted_at.date() if contract.accepted_at else date.today()
    sign_date_str = _format_date(sign_date)

    story = []
    story += _build_header(styles, sign_date_str)
    story += _build_preamble(styles, client)
    story += _build_subject(styles, rental)
    story += _build_payment(styles, rental)
    story += _build_rights(styles)
    story += _build_responsibility(styles)
    story += _build_return(styles)
    story += _build_final(styles)
    story += _build_requisites(styles, client)
    story += _build_status_line(styles, contract)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes