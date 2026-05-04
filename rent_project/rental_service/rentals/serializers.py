from rest_framework import serializers
from .models import Rental, RentalItem, Payment


class RentalItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalItem
        fields = '__all__'


class RentalSerializer(serializers.ModelSerializer):
    items = RentalItemSerializer(many=True, read_only=True)

    class Meta:
        model = Rental
        fields = '__all__'

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'
