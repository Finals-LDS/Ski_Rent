from rest_framework import serializers
from .models import Equipment, EquipmentType, EquipmentSize


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = '__all__'


class EquipmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentType
        fields = '__all__'


class EquipmentSizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentSize
        fields = '__all__'
