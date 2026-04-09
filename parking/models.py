from django.db import models

class ParkingSlot(models.Model):
    STATUS_CHOICES = (
        ('Free', 'Free'),
        ('Assigned', 'Assigned'),
    )
    # Slot ID (Primary Key) is auto-created by Django as `id`
    slot_number = models.CharField(max_length=10, unique=True)
    location = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Free')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Slot {self.slot_number} - {self.location} ({self.status})"


class ParkingRequest(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='parking_requests')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Request by {self.user.username} ({self.status})"


class SlotAssignment(models.Model):
    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Released', 'Released'),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='assignments')
    slot = models.ForeignKey(ParkingSlot, on_delete=models.CASCADE, related_name='assignments')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Active')
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.slot.slot_number} ({self.status})"

