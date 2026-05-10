from django.contrib import admin

from .models import Payment, RefundTransaction


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'rental', 'amount', 'payment_method', 'status', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('rental__contract_number', 'rental__client__full_name')


@admin.register(RefundTransaction)
class RefundTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'payment', 'amount', 'created_at')
    search_fields = ('payment__rental__contract_number',)
