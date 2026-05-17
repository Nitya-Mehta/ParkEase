import io
from contextlib import redirect_stdout

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from parking.models import ParkingSlot, SlotAssignment
from .models import Complaint


class ComplaintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123',
            role='User',
            email='testuser@example.com',
            mobile_number='9999999999',
        )
        self.admin = User.objects.create_user(
            username='adminuser',
            password='password123',
            role='Admin',
            email='adminuser@example.com',
            assigned_area='Thaltej',
        )
        self.slot = ParkingSlot.objects.create(
            slot_number='TH-B1-98',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 98',
            status='Assigned',
        )
        SlotAssignment.objects.create(user=self.user, slot=self.slot, status='Active')

    def test_user_gets_complaint_filed_confirmation(self):
        self.client.login(username='testuser', password='password123')
        image = SimpleUploadedFile(
            'vehicle.gif',
            b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
            content_type='image/gif',
        )

        terminal_output = io.StringIO()
        with redirect_stdout(terminal_output):
            response = self.client.post(
                reverse('raise_complaint'),
                {
                    'complaint_type': Complaint.COMPLAINT_TYPE_OCCUPIED,
                    'vehicle_image': image,
                },
                follow=True,
            )

        self.assertEqual(Complaint.objects.count(), 1)
        self.assertIn('PARKEASE EMAIL DRAFT', terminal_output.getvalue())
        self.assertContains(response, 'Complaint filed successfully')
        self.assertContains(response, 'solved within 5 minutes')

    def test_admin_resolve_notifies_user(self):
        complaint = Complaint.objects.create(user=self.user, slot=self.slot, vehicle_image='complaint_images/test.jpg')

        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('admin_resolve_complaint', args=[complaint.id]), follow=True)

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, 'Resolved')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['testuser@example.com'])
        self.assertIn('resolved', mail.outbox[0].subject.lower())
        self.assertContains(response, 'Email sent.')
