from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from .models import ParkingSlot, ParkingRequest, SlotAssignment

class ParkingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123', role='User')
        self.admin = User.objects.create_user(username='adminuser', password='password123', role='Admin')
        self.slot = ParkingSlot.objects.create(slot_number='A1', location='North Wing', status='Free')

    def test_slot_creation(self):
        self.assertEqual(self.slot.status, 'Free')

    def test_user_request_flow(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('submit_parking_request'))
        self.assertEqual(ParkingRequest.objects.count(), 1)
        self.assertEqual(ParkingRequest.objects.first().status, 'Pending')
        
        # Trying to request again, should fail Business Logic rule (1 active request limit)
        response = self.client.post(reverse('submit_parking_request'))
        self.assertRedirects(response, reverse('request_status'))
        self.assertEqual(ParkingRequest.objects.count(), 1) # Still 1

    def test_admin_assignment_flow(self):
        req = ParkingRequest.objects.create(user=self.user, status='Pending')
        
        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('admin_assign_slot', args=[req.id]), {'slot_id': self.slot.id})
        
        self.assertEqual(SlotAssignment.objects.count(), 1)
        req.refresh_from_db()
        self.slot.refresh_from_db()
        
        self.assertEqual(req.status, 'Approved')
        self.assertEqual(self.slot.status, 'Assigned')
        
        # Another request for the same slot should handle slot status logic elegantly
        req2 = ParkingRequest.objects.create(user=User.objects.create_user(username='user2', password='123'), status='Pending')
        response = self.client.post(reverse('admin_assign_slot', args=[req2.id]), {'slot_id': self.slot.id})
        self.assertEqual(response.status_code, 404) # 404 because slot isn't 'Free' anymore
