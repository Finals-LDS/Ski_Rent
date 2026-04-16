from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet
from .models import Client, Equipment, EquipmentType
from .serializers import ClientSerializer, EquipmentSerializer, EquipmentTypeSerializer

class ClientViewSet(ModelViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

class EquipmentViewSet(ModelViewSet):
    queryset = Equipment.objects.all()
    serializer_class = EquipmentSerializer

class EquipmentTypeViewSet(ModelViewSet):
    queryset = EquipmentType.objects.all()
    serializer_class = EquipmentTypeSerializer 