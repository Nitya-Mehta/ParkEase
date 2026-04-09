from django.db import models

class Complaint(models.Model):
    STATUS_CHOICES = (
        ('Open', 'Open'),
        ('Resolved', 'Resolved'),
    )
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='complaints')
    slot = models.ForeignKey('parking.ParkingSlot', on_delete=models.CASCADE, related_name='complaints')
    vehicle_image = models.ImageField(upload_to='complaint_images/')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Complaint by {self.user.username} - Slot {self.slot.slot_number} ({self.status})"
