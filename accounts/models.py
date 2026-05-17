from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    AREA_CHOICES = (
        ('Thaltej', 'Thaltej'),
        ('Navrangpura', 'Navrangpura'),
        ('Paldi', 'Paldi'),
        ('Kalupur', 'Kalupur'),
    )
    ROLE_CHOICES = (
        ('Admin', 'Admin'),
        ('User', 'User'),
    )
    PASS_CHOICES = (
        ('Free', 'Free Pass'),
        ('Pro', 'Pro Pass'),
        ('Premium', 'Premium Pass'),
    )
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    vehicle_number = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='User')
    assigned_area = models.CharField(max_length=20, choices=AREA_CHOICES, blank=True, null=True)
    parking_pass = models.CharField(max_length=10, choices=PASS_CHOICES, default='Free')

    @property
    def parking_pass_label(self):
        return dict(self.PASS_CHOICES).get(self.parking_pass, self.parking_pass)

    @property
    def booking_window_days(self):
        return 3 if self.parking_pass == 'Free' else 3650

    @property
    def can_use_auto_booking(self):
        return self.parking_pass in {'Pro', 'Premium'}

    @property
    def can_book_vip_slots(self):
        return self.parking_pass == 'Premium'

    @property
    def approval_priority(self):
        return {
            'Premium': 0,
            'Pro': 1,
            'Free': 2,
        }.get(self.parking_pass, 2)

    @property
    def parking_discount_rate(self):
        return {
            'Premium': 20,
            'Pro': 10,
            'Free': 0,
        }.get(self.parking_pass, 0)

    @property
    def saved_vehicle_numbers(self):
        numbers = []
        seen = set()
        for plate in [self.vehicle_number, *self.saved_vehicles.values_list('plate_number', flat=True)]:
            normalized = UserVehicle.normalize_plate_number(plate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                numbers.append(normalized)
        return numbers

    def can_book_date(self, selected_date):
        if not selected_date:
            return False
        max_date = timezone.localdate() + timezone.timedelta(days=self.booking_window_days)
        return selected_date <= max_date

    def __str__(self):
        return f"{self.username} ({self.role})"


class UserVehicle(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_vehicles')
    nickname = models.CharField(max_length=40, blank=True)
    plate_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'plate_number'], name='unique_user_saved_vehicle'),
        ]

    @staticmethod
    def normalize_plate_number(value):
        return ''.join(char for char in (value or '').upper() if char.isalnum())

    def save(self, *args, **kwargs):
        self.plate_number = self.normalize_plate_number(self.plate_number)
        super().save(*args, **kwargs)

    def __str__(self):
        label = self.nickname or self.plate_number
        return f'{self.user.username} - {label}'
