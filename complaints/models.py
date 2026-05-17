from django.db import models

class Complaint(models.Model):
    COMPLAINT_TYPE_OCCUPIED = 'Parking spot occupied'
    COMPLAINT_TYPE_BLOCKED = 'Vehicle blocking access'
    COMPLAINT_TYPE_DAMAGE = 'Parking area damage'
    COMPLAINT_TYPE_LIGHTING = 'Poor lighting or security issue'
    COMPLAINT_TYPE_OTHER = 'Other'

    STATUS_CHOICES = (
        ('Open', 'Open'),
        ('Resolved', 'Resolved'),
    )
    COMPLAINT_TYPE_CHOICES = (
        (COMPLAINT_TYPE_OCCUPIED, COMPLAINT_TYPE_OCCUPIED),
        (COMPLAINT_TYPE_BLOCKED, COMPLAINT_TYPE_BLOCKED),
        (COMPLAINT_TYPE_DAMAGE, COMPLAINT_TYPE_DAMAGE),
        (COMPLAINT_TYPE_LIGHTING, COMPLAINT_TYPE_LIGHTING),
        (COMPLAINT_TYPE_OTHER, COMPLAINT_TYPE_OTHER),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='complaints')
    slot = models.ForeignKey('parking.ParkingSlot', on_delete=models.CASCADE, related_name='complaints')
    complaint_type = models.CharField(
        max_length=80,
        choices=COMPLAINT_TYPE_CHOICES,
        default=COMPLAINT_TYPE_OCCUPIED,
    )
    complaint_details = models.TextField(blank=True)
    vehicle_image = models.ImageField(upload_to='complaint_images/')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.complaint_type} by {self.user.username} - Slot {self.slot.slot_number} ({self.status})"
