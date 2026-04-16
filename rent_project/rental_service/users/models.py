from django.db import models


from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):

    ROLE_CHOICES = (
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("cashier", "Cashier"),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="cashier"
    )