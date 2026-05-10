from rest_framework import serializers

from .models import Payment, RefundTransaction


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'


class RefundTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RefundTransaction
        fields = '__all__'
