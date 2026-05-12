from django.db import models


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
    size = models.CharField(max_length=20, blank=True, null=True)
    has_sizes = models.BooleanField(default=True, verbose_name='Есть размеры')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=0)
    quantity_rented = models.IntegerField(default=0)

    @property
    def quantity_available(self):
        if self.has_sizes and self.sizes.exists():
            return sum(size.quantity_available for size in self.sizes.all())

        return self.quantity - self.quantity_rented

    @property
    def total_quantity(self):
        if self.has_sizes and self.sizes.exists():
            return sum(size.quantity for size in self.sizes.all())

        return self.quantity

    @property
    def total_rented(self):
        if self.has_sizes and self.sizes.exists():
            return sum(size.quantity_rented for size in self.sizes.all())

        return self.quantity_rented

    def __str__(self):
        return self.name


class EquipmentSize(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='sizes')
    size = models.CharField(max_length=20, verbose_name='Размер')
    quantity = models.IntegerField(default=1, verbose_name='Кол-во')
    quantity_rented = models.IntegerField(default=0, verbose_name='В аренде')

    @property
    def quantity_available(self):
        return max(self.quantity - self.quantity_rented, 0)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        equipment = self.equipment

        equipment.quantity = equipment.total_quantity
        equipment.quantity_rented = equipment.total_rented

        if equipment.quantity_rented > 0:
            equipment.status = 'rented'
        else:
            equipment.status = 'available'

        equipment.save(update_fields=['quantity', 'quantity_rented', 'status'])

    def delete(self, *args, **kwargs):
        equipment = self.equipment

        super().delete(*args, **kwargs)

        equipment.quantity = equipment.total_quantity
        equipment.quantity_rented = equipment.total_rented

        if equipment.quantity_rented > 0:
            equipment.status = 'rented'
        else:
            equipment.status = 'available'

        equipment.save(update_fields=['quantity', 'quantity_rented', 'status'])

    def __str__(self):
        return f'{self.equipment.name} - {self.size}'

    class Meta:
        unique_together = ('equipment', 'size')
        verbose_name = 'Размер'
        verbose_name_plural = 'Размеры'
