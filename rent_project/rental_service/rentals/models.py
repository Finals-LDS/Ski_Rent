from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from clients.models import Client
from equipment.models import Equipment
import uuid


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
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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