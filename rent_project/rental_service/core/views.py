from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rentals.models import Rental
from equipment.models import Equipment
from rest_framework.permissions import IsAuthenticated

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "id": request.user.id,
            "username": request.user.username
        })

class DashboardView(APIView):
    def get(self, request):
        return Response({
            "total_equipment": Equipment.objects.count(),
            "active_rentals": Rental.objects.filter(status='active').count(),
            "revenue": sum(r.total_price for r in Rental.objects.all())
        })
        
        