from decimal import Decimal
from math import ceil

from django.db import models
from django.utils import timezone

class ParkingSlot(models.Model):
    AREA_CHOICES = (
        ('Thaltej', 'Thaltej'),
        ('Navrangpura', 'Navrangpura'),
        ('Paldi', 'Paldi'),
        ('Kalupur', 'Kalupur'),
    )
    BASEMENT_CHOICES = (
        ('B1', 'Basement -1'),
        ('B2', 'Basement -2'),
        ('B3', 'Basement -3'),
    )
    STATUS_CHOICES = (
        ('Free', 'Free'),
        ('Assigned', 'Assigned'),
    )
    # Slot ID (Primary Key) is auto-created by Django as `id`
    slot_number = models.CharField(max_length=10, unique=True)
    area = models.CharField(max_length=20, choices=AREA_CHOICES, default='Thaltej')
    basement_level = models.CharField(max_length=2, choices=BASEMENT_CHOICES, default='B1')
    location = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Free')
    vip_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    @property
    def full_location(self):
        return f"{self.area} - {self.get_basement_level_display()}"

    @property
    def is_vip(self):
        return self.vip_only or 'VIP' in (self.slot_number or '').upper()

    def __str__(self):
        return f"Slot {self.slot_number} - {self.full_location} ({self.status})"


class ParkingRequest(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Cancelled', 'Cancelled'),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='parking_requests')
    requested_slot = models.ForeignKey(
        ParkingSlot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_by',
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')
    requested_start_time = models.DateTimeField(null=True, blank=True)
    duration_hours = models.PositiveIntegerField(default=2)
    vehicle_plate_number = models.CharField(max_length=20, blank=True)
    is_auto_booked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def requested_end_time(self):
        if not self.requested_start_time:
            return None
        return self.requested_start_time + timezone.timedelta(hours=self.duration_hours)

    @property
    def booking_date(self):
        if not self.requested_start_time:
            return None
        return timezone.localtime(self.requested_start_time).date()

    def __str__(self):
        requested = self.requested_slot.slot_number if self.requested_slot else 'No slot selected'
        return f"Request by {self.user.username} for {requested} ({self.status})"


class SlotAssignment(models.Model):
    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Released', 'Released'),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='assignments')
    slot = models.ForeignKey(ParkingSlot, on_delete=models.CASCADE, related_name='assignments')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Active')
    assigned_at = models.DateTimeField(auto_now_add=True)
    entered_at = models.DateTimeField(null=True, blank=True)
    booked_start_time = models.DateTimeField(null=True, blank=True)
    booked_end_time = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    booked_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    overstay_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    vehicle_plate_number = models.CharField(max_length=20, blank=True)

    FIRST_HOUR_RATE = Decimal('50.00')
    ADDITIONAL_HOUR_RATE = Decimal('30.00')

    @property
    def effective_start_time(self):
        return self.booked_start_time or self.assigned_at

    @property
    def effective_end_time(self):
        if self.booked_end_time:
            return self.booked_end_time
        return self.effective_start_time + timezone.timedelta(hours=2)

    @property
    def is_currently_parked(self):
        return self.status == 'Active' and self.entered_at is not None and self.released_at is None

    @property
    def parking_started_at(self):
        return self.entered_at or self.booked_start_time or self.assigned_at

    @property
    def parking_duration_minutes(self):
        start_time = self.parking_started_at
        if not start_time:
            return 0
        end_time = self.released_at or timezone.now()
        if end_time <= start_time:
            return 0
        return int((end_time - start_time).total_seconds() // 60)

    @property
    def parking_duration_display(self):
        minutes = self.parking_duration_minutes
        hours, remaining_minutes = divmod(minutes, 60)
        if hours and remaining_minutes:
            return f'{hours}h {remaining_minutes}m'
        if hours:
            return f'{hours}h'
        return f'{remaining_minutes}m'

    @property
    def parking_fee(self):
        minutes = self.parking_duration_minutes
        if minutes <= 0:
            return Decimal('0.00')
        base_fee = self.base_parking_fee
        if base_fee <= 0:
            return Decimal('0.00')
        discount_rate = Decimal(self.user.parking_discount_rate or 0)
        if discount_rate <= 0:
            return base_fee
        discounted_fee = base_fee * (Decimal('1.00') - (discount_rate / Decimal('100')))
        return discounted_fee.quantize(Decimal('0.01'))

    @property
    def base_parking_fee(self):
        minutes = self.parking_duration_minutes
        if minutes <= 0:
            return Decimal('0.00')
        if minutes <= 60:
            return self.FIRST_HOUR_RATE
        extra_minutes = minutes - 60
        extra_hours = ceil(extra_minutes / 60)
        return self.FIRST_HOUR_RATE + (self.ADDITIONAL_HOUR_RATE * Decimal(extra_hours))

    @property
    def parking_discount_amount(self):
        return (self.base_parking_fee - self.parking_fee).quantize(Decimal('0.01'))

    @property
    def is_overstayed(self):
        return self.is_currently_parked and timezone.now() > self.effective_end_time

    @property
    def overstay_minutes(self):
        if not self.is_overstayed:
            return 0
        return int((timezone.now() - self.effective_end_time).total_seconds() // 60)

    @property
    def total_amount(self):
        return self.parking_fee + (self.overstay_amount or Decimal('0.00'))

    def __str__(self):
        return f"{self.user.username} - {self.slot.slot_number} ({self.status})"


class AutoBookingRule(models.Model):
    WEEKDAY_CHOICES = (
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    )

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='auto_booking_rules')
    requested_slot = models.ForeignKey(ParkingSlot, on_delete=models.CASCADE, related_name='auto_booking_rules')
    vehicle_plate_number = models.CharField(max_length=20)
    weekdays = models.CharField(max_length=32)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    last_generated_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    @property
    def weekday_numbers(self):
        return [int(value) for value in self.weekdays.split(',') if value != '']

    @property
    def weekday_labels(self):
        labels = dict(self.WEEKDAY_CHOICES)
        return [labels.get(str(value), str(value)) for value in self.weekday_numbers]

    def __str__(self):
        return f'{self.user.username} auto-booking for {self.requested_slot.slot_number}'


class VehicleScanLog(models.Model):
    SOURCE_CHOICES = (
        ('camera', 'Camera'),
        ('upload', 'Upload'),
    )
    GATE_MODE_CHOICES = (
        ('entry', 'Entry'),
        ('exit', 'Exit'),
    )
    STATUS_CHOICES = (
        ('authorized', 'Authorized'),
        ('already_inside', 'Already Inside'),
        ('exited', 'Exited'),
        ('already_outside', 'Already Outside'),
        ('no_booking', 'No Booking'),
        ('unregistered', 'Unregistered'),
        ('unreadable', 'Unreadable'),
    )

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='upload')
    gate_mode = models.CharField(max_length=10, choices=GATE_MODE_CHOICES, default='entry')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unreadable')
    scan_image = models.ImageField(upload_to='anpr_scans/')
    detected_plate = models.CharField(max_length=20, blank=True)
    bounding_box = models.JSONField(default=dict, blank=True)
    matched_user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicle_scan_logs',
    )
    matched_assignment = models.ForeignKey(
        SlotAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicle_scan_logs',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        plate = self.detected_plate or 'Unknown plate'
        return f'{plate} - {self.get_status_display()}'

