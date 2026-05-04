from django.db import models
from datetime import date


class Client(models.Model):
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(max_length=100, blank=True)
    document_id = models.CharField(max_length=50, blank=True)
    birth_date = models.DateField(null=True, blank=True, verbose_name='Дата рождения')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name

    @property
    def is_birthday_today(self):
        """Проверяет, сегодня ли день рождения клиента."""
        if not self.birth_date:
            return False
        today = date.today()
        return self.birth_date.day == today.day and self.birth_date.month == today.month

    @property
    def age(self):
        """Возраст клиента."""
        if not self.birth_date:
            return None
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )
