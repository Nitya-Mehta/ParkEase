from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User
from parking.models import ParkingSlot, ParkingRequest, SlotAssignment

class CustomUserAdmin(UserAdmin):
    model = User

    list_display = ('username', 'email', 'role', 'is_staff')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('email', 'mobile_number', 'vehicle_number')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Role Info', {'fields': ('role',)}),
        ('Important Dates', {'fields': ('last_login',)}),
    )


admin.site.register(User, CustomUserAdmin)
admin.site.register(ParkingSlot)
admin.site.register(ParkingRequest)
admin.site.register(SlotAssignment)
