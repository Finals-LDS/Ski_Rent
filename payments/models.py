from django.db import models
from rentals.models import Rental


class Payment(models.Model):
    STATUS_CHOICES = [
        ("paid", "Оплачено"),
        ("partially_refunded", "Частично возвращено"),
        ("refunded", "Полностью возвращено"),
    ]

    rental = models.ForeignKey(Rental, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="paid")
    created_at = models.DateTimeField(auto_now_add=True)

    def refunded_total(self):
        return sum(r.amount for r in self.refunds.all())

    def available_for_refund(self):
        return self.amount - self.refunded_total()

    def __str__(self):
        return f'{self.rental.client.full_name} - {self.amount}'

class RefundTransaction(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Refund {self.amount} for Payment {self.payment_id}"