from rest_framework import serializers

from .models import Contract, Discount, PriceModifier, Rental, RentalItem, Signature


class RentalItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalItem
        fields = '__all__'


class RentalSerializer(serializers.ModelSerializer):
    items = RentalItemSerializer(many=True, read_only=True)

    class Meta:
        model = Rental
        fields = '__all__'


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = '__all__'


class SignatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Signature
        fields = '__all__'


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = '__all__'


class PriceModifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceModifier
        fields = '__all__'
