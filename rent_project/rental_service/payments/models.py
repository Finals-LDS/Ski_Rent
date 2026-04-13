from django.db import models
from rentals.models import Rental


class Payment(models.Model):
    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.rental.client.full_name} - {self.amount}'