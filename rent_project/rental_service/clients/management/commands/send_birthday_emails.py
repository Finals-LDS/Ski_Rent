"""
Management command: python manage.py send_birthday_emails
Отправляет поздравление с Днём Рождения всем клиентам, у кого сегодня ДР.
Запускать через cron ежедневно в 09:00.
"""
import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

from clients.models import Client

logger = logging.getLogger(__name__)


BIRTHDAY_EMAIL_SUBJECT = "🎉 С Днём Рождения от Ski Rent!"

BIRTHDAY_EMAIL_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0e1117; color: #e6edf3; margin: 0; padding: 0; }}
    .container {{ max-width: 560px; margin: 40px auto; background: #161b22; border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08); }}
    .header {{ background: linear-gradient(135deg, #4facfe, #00f2fe); padding: 40px 32px; text-align: center; }}
    .header h1 {{ color: #fff; font-size: 28px; margin: 0 0 8px; }}
    .header p {{ color: rgba(255,255,255,0.85); font-size: 15px; margin: 0; }}
    .body {{ padding: 32px; }}
    .greeting {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; }}
    .message {{ font-size: 15px; color: rgba(230,237,243,0.8); line-height: 1.6; margin-bottom: 24px; }}
    .promo-box {{ background: rgba(79,172,254,0.08); border: 1px solid rgba(79,172,254,0.25); border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 24px; }}
    .promo-box .discount {{ font-size: 48px; font-weight: 800; color: #4facfe; line-height: 1; }}
    .promo-box .label {{ font-size: 13px; color: rgba(230,237,243,0.6); margin-top: 6px; }}
    .promo-code {{ background: rgba(255,255,255,0.05); border: 1px dashed rgba(79,172,254,0.4); border-radius: 8px; padding: 12px 20px; font-family: monospace; font-size: 20px; letter-spacing: 3px; color: #4facfe; font-weight: 700; text-align: center; margin-bottom: 24px; }}
    .footer {{ padding: 20px 32px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 12px; color: rgba(230,237,243,0.35); text-align: center; }}
    .emoji-big {{ font-size: 48px; display: block; text-align: center; margin-bottom: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🎿 Ski Rent</h1>
      <p>Горнолыжный прокат — всё для идеального спуска</p>
    </div>
    <div class="body">
      <span class="emoji-big">🎂</span>
      <div class="greeting">Дорогой(ая) {full_name},</div>
      <div class="message">
        Команда <strong>Ski Rent</strong> поздравляет вас с Днём Рождения! Желаем вам солнечных склонов, скоростных спусков и незабываемых приключений! 🏔️
      </div>
      <div class="promo-box">
        <div class="discount">{discount_percent}%</div>
        <div class="label">скидка на аренду снаряжения в ваш особый день</div>
      </div>
      <div style="font-size: 13px; color: rgba(230,237,243,0.6); margin-bottom: 8px; text-align: center;">Ваш промокод:</div>
      <div class="promo-code">BDAY{promo_suffix}</div>
      <div class="message" style="font-size: 13px; text-align: center;">
        Промокод действует сегодня. Просто назовите его при оформлении аренды или покажите это письмо нашему сотруднику.
      </div>
    </div>
    <div class="footer">
      Ski Rent &bull; Алматы &bull; Это письмо отправлено автоматически, отвечать на него не нужно.
    </div>
  </div>
</body>
</html>
"""

BIRTHDAY_EMAIL_TEXT = """
Дорогой(ая) {full_name},

С Днём Рождения! 🎉

Команда Ski Rent поздравляет вас и дарит скидку {discount_percent}% на аренду снаряжения!

Ваш промокод: BDAY{promo_suffix}
Промокод действует сегодня.

С уважением,
Команда Ski Rent
"""


class Command(BaseCommand):
    help = 'Отправляет поздравительные письма клиентам с Днём Рождения'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать список именинников без отправки писем',
        )
        parser.add_argument(
            '--discount',
            type=int,
            default=15,
            help='Процент скидки в поздравительном письме (по умолчанию 15)',
        )

    def handle(self, *args, **options):
        today = date.today()
        dry_run = options['dry_run']
        discount_percent = options['discount']

        birthday_clients = Client.objects.filter(
            birth_date__day=today.day,
            birth_date__month=today.month,
            email__isnull=False,
        ).exclude(email='')

        count = birthday_clients.count()
        self.stdout.write(f'Именинников сегодня ({today.strftime("%d.%m")}): {count}')

        if dry_run:
            for c in birthday_clients:
                self.stdout.write(f'  - {c.full_name} <{c.email}>')
            return

        sent = 0
        failed = 0
        for client in birthday_clients:
            promo_suffix = f"{client.id:04d}{today.strftime('%m%d')}"
            html_body = BIRTHDAY_EMAIL_HTML.format(
                full_name=client.full_name,
                discount_percent=discount_percent,
                promo_suffix=promo_suffix,
            )
            text_body = BIRTHDAY_EMAIL_TEXT.format(
                full_name=client.full_name,
                discount_percent=discount_percent,
                promo_suffix=promo_suffix,
            )
            try:
                msg = EmailMultiAlternatives(
                    subject=BIRTHDAY_EMAIL_SUBJECT,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[client.email],
                )
                msg.attach_alternative(html_body, "text/html")
                msg.send(fail_silently=False)
                sent += 1
                self.stdout.write(self.style.SUCCESS(f'  ✓ {client.full_name} <{client.email}>'))
            except Exception as exc:
                failed += 1
                logger.error('Birthday email error for client %s: %s', client.id, exc)
                self.stdout.write(self.style.ERROR(f'  ✗ {client.full_name}: {exc}'))

        self.stdout.write(f'\nОтправлено: {sent}, ошибок: {failed}')
