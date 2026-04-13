from rest_framework import serializers
from .models import Rental, RentalItem


class RentalItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalItem
        fields = '__all__'


class RentalSerializer(serializers.ModelSerializer):
    items = RentalItemSerializer(many=True, read_only=True)

    class Meta:
        model = Rental
        fields = '__all__'