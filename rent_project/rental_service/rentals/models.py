from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from clients.models import Client
from django.conf import settings
from equipment.models import Equipment
import uuid
from django.utils import timezone
from datetime import timedelta

class SmsOTP(models.Model):
    contract_id = models.IntegerField()
    phone = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(seconds=120)


class Rental(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('open', 'Открыт'),
        ('booked', 'Забронирован'),
        ('rented', 'Арендован'),
        ('completed', 'Завершён'),
        ('canceled', 'Отменён'),
    ]

    contract_number = models.CharField(max_length=20, unique=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='rentals', null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'Дата окончания не может быть раньше даты начала.'})

    def generate_contract_number(self):
        count = Rental.objects.count() + 1
        return f'C{count:03d}'

    @property
    def rental_days(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0

    def calculate_total_price(self):
        total = Decimal('0.00')
        for item in self.items.all():
            total += Decimal(item.days) * item.price_per_day
        return total

    def save(self, *args, **kwargs):
        if not self.contract_number:
            self.contract_number = self.generate_contract_number()
        update_fields = kwargs.get('update_fields')
        if not update_fields:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.contract_number


class RentalItem(models.Model):
    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name='items')
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE)
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    days = models.IntegerField(default=1)

    def get_total(self):
        return self.price_per_day * self.days

    def save(self, *args, **kwargs):
        if not self.price_per_day:
            self.price_per_day = self.equipment.price_per_day
        super().save(*args, **kwargs)
        rental = self.rental
        rental.total_price = rental.calculate_total_price()
        rental.save(update_fields=['total_price'])

    def __str__(self):
        return f'{self.rental.contract_number} — {self.equipment.name}'


class Discount(models.Model):
    name = models.CharField(max_length=100)
    percent = models.IntegerField()
    min_days = models.IntegerField()

    def __str__(self):
        return self.name


class PriceModifier(models.Model):
    weekday_multiplier = models.FloatField(default=1.0)
    holiday_multiplier = models.FloatField(default=1.0)

    class Meta:
        verbose_name = 'Модификатор цены'

    def __str__(self):
        return 'Модификаторы цены'
    
class Payment(models.Model):
    rental = models.ForeignKey(Rental, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

class Contract(models.Model):
    STATUS_CHOICES = [
        ('draft',       'Черновик'),
        ('sent',        'Отправлен'),
        ('signed_card', 'Подписан через ЭЦП'),   # ← новый (карт-ридер)
        ('signed_sms',  'Подписан через SMS'),    # ← новый (SMS)
        ('accepted',    'Принят'),                # ← старый (совместимость)
        ('rejected',    'Отклонён'),
    ]

    client         = models.ForeignKey('clients.Client', on_delete=models.CASCADE)
    rental         = models.OneToOneField('rentals.Rental', on_delete=models.CASCADE)
    text           = models.TextField()
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    accepted_at    = models.DateTimeField(null=True, blank=True)
    signature_data = models.TextField(null=True, blank=True)  # сырой XML из NCALayer
    created_at     = models.DateTimeField(auto_now_add=True)

    @property
    def is_signed(self):
        return self.status in ('signed_card', 'signed_sms', 'accepted')

    def __str__(self):
        return f'Договор #{self.id} ({self.client.full_name})'


class Signature(models.Model):
    METHOD_SMS  = 'sms'
    METHOD_CARD = 'card'
    METHOD_CHOICES = [
        (METHOD_CARD, 'ЭЦП (карт-ридер / NCALayer)'),
        (METHOD_SMS,  'SMS OTP'),
    ]

    contract   = models.ForeignKey(
        Contract, on_delete=models.CASCADE,
        related_name='signatures', verbose_name='Договор',
    )
    operator = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='signatures',

        verbose_name='Оператор',

    )
    method     = models.CharField(
        max_length=10, choices=METHOD_CHOICES,
        default=METHOD_CARD, verbose_name='Способ подписания',
    )
    # Для карт-ридера: base64-XML из NCALayer
    # Для SMS: хэш OTP или метка
    raw_signature = models.TextField(verbose_name='Данные подписи (raw)')
    signed_at     = models.DateTimeField(auto_now_add=True, verbose_name='Дата и время')

    class Meta:
        verbose_name        = 'Подпись'
        verbose_name_plural = 'Подписи'
        ordering            = ['-signed_at']

    def __str__(self):
        return f'[{self.get_method_display()}] Договор #{self.contract_id} — {self.signed_at:%d.%m.%Y %H:%M}'
