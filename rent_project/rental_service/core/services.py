from rentals.models import Rental
from .models import Discount

def calculate_rental_price(rental: Rental):
    total = 0

    for item in rental.items.all():
        total += item.price_per_day * item.days

    discount = Discount.objects.filter(min_days_lte=item.days).order_by('-percent').first()

    if discount:
        total = total * (1 - discount.percent / 100)

    rental.total_price = total
    rental.save()

    return total