from django.contrib import admin
from .models import Equipment, EquipmentType, EquipmentSize

class EquipmentSizeInLine(admin.TabularInline):
    model = EquipmentSize
    eztra = 1


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    inlines = [EquipmentSizeInLine]
    list_display = ['name', 'type', 'has_sizes', 'size', 'status', 'price_per_day', 'quantity']

@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    pass 

@admin.register(EquipmentSize)
class EquipmentSizeAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'size', 'quantity', 'quantity_rented', 'quantity_available']