from django.contrib import admin
from .models import Equipment, EquipmentType, EquipmentSize

admin.site.register(Equipment)
admin.site.register(EquipmentType)
admin.site.register(EquipmentSize)
