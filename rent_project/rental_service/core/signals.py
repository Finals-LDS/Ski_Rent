from django.db.models.signals import post_save
from django.dispatch import receiver
from rentals.models import RentalItem
from .services import calculate_rental_price


@receiver(post_save, sender=RentalItem)
def update_rental_price(sender, instance, **kwargs):
    calculate_rental_price(instance.rental)