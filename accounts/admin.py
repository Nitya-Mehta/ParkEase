from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, UserVehicle
from parking.models import ParkingSlot, ParkingRequest, SlotAssignment

class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('mobile_number', 'vehicle_number', 'parking_pass', 'role', 'assigned_area')}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(UserVehicle)
admin.site.register(ParkingSlot)
admin.site.register(ParkingRequest)
admin.site.register(SlotAssignment)
