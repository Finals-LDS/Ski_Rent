from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import RentalItem

@receiver(post_save, sender=RentalItem)
def update_rental_total(sender, instance, **kwargs):
    rental = isinstance.rental
    total = sum(item.get.total() for item in rental.items.all())
    rental.total_price = total
    rental.save()