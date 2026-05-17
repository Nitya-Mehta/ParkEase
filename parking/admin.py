from django.contrib import admin

from .models import AutoBookingRule, VehicleScanLog


admin.site.register(VehicleScanLog)
admin.site.register(AutoBookingRule)
