from django.db import models

# Create your models here.

class Client(models.Model):
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.CharField(max_length=100, blank=True, null=True)
    document_id = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name