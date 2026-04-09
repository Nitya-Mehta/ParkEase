from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('mobile_number', 'vehicle_number', 'role')}),
    )

admin.site.register(User, CustomUserAdmin)
