from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from clients.models import Client
from equipment.models import Equipment


class Rental(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('open', 'Открыт'),
        ('booked', 'Забронирован'),
        ('rented', 'Арендован'),
        ('completed', 'Завершён'),
        ('canceled', 'Отменён'),
    ]

    discount = models.ForeignKey(
        'Discount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rentals',
        verbose_name='Скидка',
    )

    contract_number = models.CharField(max_length=20, unique=True, blank=True)
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE,
        related_name='rentals', null=True, blank=True,
    )
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
        # Используем max(id)+1 вместо count(), чтобы избежать
        # дублирования при удалённых записях.
        last = Rental.objects.order_by('-id').values_list('id', flat=True).first()
        seq = (last + 1) if last else 1
        candidate = f'C{seq:03d}'
        while Rental.objects.filter(contract_number=candidate).exists():
            seq += 1
            candidate = f'C{seq:03d}'
        return candidate

    @property
    def rental_days(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0

    def calculate_total_price(self):
        total = Decimal('0.00')

        if not self.start_date:
            return total

        modifier = PriceModifier.objects.first()

        weekday_multiplier = Decimal('1.0')
        holiday_multiplier = Decimal('1.0')

        if modifier:
            weekday_multiplier = Decimal(str(modifier.weekday_multiplier))
            holiday_multiplier = Decimal(str(modifier.holiday_multiplier))

        for item in self.items.all():
            item_total = Decimal('0.00')

            for day_offset in range(item.days):
                current_day = self.start_date + timedelta(days=day_offset)

                daily_price = item.price_per_day

                # Суббота = 5, воскресенье = 6
                if current_day.weekday() in [5, 6]:
                    daily_price *= weekday_multiplier

                # Заглушка для праздников
                # Позже можно подключить holidays KZ
                if False:
                    daily_price *= holiday_multiplier

                item_total += daily_price * Decimal(item.quantity)

            total += item_total

        if self.discount:
            discount_amount = total * Decimal(self.discount.percent) / Decimal('100')
            total -= discount_amount

        return total.quantize(Decimal('0.01'))

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
    size = models.CharField(max_length=20, blank=True, default='', verbose_name='Размер')
    quantity = models.PositiveIntegerField(default=1, verbose_name='Кол-во')

    def get_total(self):
        return self.price_per_day * self.days * self.quantity

    def save(self, *args, **kwargs):
        if not self.price_per_day:
            self.price_per_day = self.equipment.price_per_day
        if self.quantity < 1:
            self.quantity = 1
        super().save(*args, **kwargs)
        # Recalculate parent rental total
        rental = self.rental
        rental.total_price = rental.calculate_total_price()
        rental.save(update_fields=['total_price'])

    def __str__(self):
        size_str = f' (p.{self.size})' if self.size else ''
        qty_str = f' x{self.quantity}' if self.quantity > 1 else ''
        return f'{self.rental.contract_number} — {self.equipment.name}{size_str}{qty_str}'


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


class Contract(models.Model):
    STATUS_CHOICES = [
        ('draft',       'Черновик'),
        ('sent',        'Отправлен'),
        ('signed_card', 'Подписан через ЭЦП'),
        ('signed_sms',  'Подписан через SMS'),
        ('accepted',    'Принят'),
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
    METHOD_SMS = 'sms'
    METHOD_CARD = 'card'
    METHOD_CHOICES = [
        (METHOD_CARD, 'ЭЦП (карт-ридер / NCALayer)'),
        (METHOD_SMS,  'SMS OTP'),
    ]

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE,
        related_name='signatures', verbose_name='Договор',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='signatures',
        verbose_name='Оператор',
    )
    method = models.CharField(
        max_length=10, choices=METHOD_CHOICES,
        default=METHOD_CARD, verbose_name='Способ подписания',
    )
    # Для карт-ридера: base64-XML из NCALayer
    # Для SMS: хэш OTP или метка
    raw_signature = models.TextField(verbose_name='Данные подписи (raw)')
    signed_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата и время')

    class Meta:
        verbose_name = 'Подпись'
        verbose_name_plural = 'Подписи'
        ordering = ['-signed_at']

    def __str__(self):
        return f'[{self.get_method_display()}] Договор #{self.contract_id} — {self.signed_at:%d.%m.%Y %H:%M}'
