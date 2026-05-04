from django.db import models
from django.contrib.auth.models import User
from django.conf import settings


class EquipmentType(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Equipment(models.Model):
    STATUS_CHOICES = [
        ('available', 'Доступно'),
        ('rented', 'В аренде'),
        ('repair', 'Ремонт'),
    ]

    name = models.CharField(max_length=100)
    type = models.ForeignKey(EquipmentType, on_delete=models.CASCADE, related_name='equipment')
    size = models.CharField(max_length=20, blank=True)
    has_sizes = models.BooleanField(default=False, verbose_name='Есть размеры')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    quantity_rented = models.IntegerField(default=0)

    @property
    def quantity_available(self):
        return self.quantity - self.quantity_rented

    def __str__(self):
        return self.name
    
class Client(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)

    iin = models.CharField(max_length=12, unique=True)
    document_id = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name

class EquipmentSize(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='sizes')
    size = models.CharField(max_length=20, verbose_name='Размер')
    quantity = models.IntegerField(default=1, verbose_name='Кол-во')
    quantity_rented = models.IntegerField(default=0, verbose_name='В аренде')

    @property
    def quantity_available(self):
        return self.quantity - self.quantity_rented

    def __str__(self):
        return f'{self.equipment.name} - {self.size}'

    class Meta:
        unique_together = ('equipment', 'size')
        verbose_name = 'Размер'
        verbose_name_plural = 'Размеры'