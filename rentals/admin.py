from django.contrib import admin

from .models import Contract, Discount, PriceModifier, Rental, Signature


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display  = ('contract_number', 'client', 'status', 'start_date', 'end_date', 'total_price')
    list_filter   = ('status',)
    search_fields = ('contract_number', 'client__full_name')


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display    = ('id', 'client', 'rental', 'status', 'accepted_at', 'created_at')
    list_filter     = ('status',)
    search_fields   = ('client__full_name', 'rental__contract_number')
    readonly_fields = ('created_at', 'accepted_at')


@admin.register(Signature)
class SignatureAdmin(admin.ModelAdmin):
    list_display    = ('id', 'contract', 'method', 'operator', 'signed_at')
    list_filter     = ('method',)
    search_fields   = ('contract__id', 'operator__username')
    readonly_fields = ('signed_at',)


admin.site.register(Discount)
admin.site.register(PriceModifier)
