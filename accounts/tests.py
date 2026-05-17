from unittest.mock import patch
import hashlib
import hmac

from django.test import TestCase, override_settings
from django.urls import reverse
from .models import User, UserVehicle
from .views import build_subscription_callback_token
from parking.models import ParkingSlot, SlotAssignment

class AccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123',
            role='User',
            vehicle_number='GJ01AB1234',
        )
        self.admin = User.objects.create_user(
            username='adminuser',
            password='password123',
            role='Admin',
            assigned_area='Thaltej',
        )
        self.superadmin = User.objects.create_superuser(
            username='superadmin',
            password='password123',
            email='superadmin@example.com',
            role='Admin',
            assigned_area='Navrangpura',
        )

    def test_user_creation(self):
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.role, 'User')
        self.assertEqual(self.user.parking_pass, 'Free')

    def test_login_redirect(self):
        # Admin login
        self.client.login(username='adminuser', password='password123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.client.logout()
        
        # User login
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('user_dashboard'))
        self.client.logout()

    def test_admin_decorators(self):
        # User accessing admin dashboard
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_admin_dashboard_scoped_area(self):
        self.client.login(username='adminuser', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_area'], 'Thaltej')
        self.assertEqual(response.context['admin_scope_area'], 'Thaltej')
        self.assertContains(response, 'Request Status Breakdown')
        self.assertContains(response, 'Area Capacity Overview')

    def test_superuser_sees_create_admin_nav_link(self):
        self.client.login(username='superadmin', password='password123')
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Admin')

    def test_superuser_can_create_admin_account(self):
        self.client.login(username='superadmin', password='password123')
        response = self.client.post(reverse('create_admin'), {
            'username': 'newadmin',
            'email': 'newadmin@example.com',
            'first_name': 'New',
            'last_name': 'Admin',
            'mobile_number': '9876543210',
            'assigned_area': 'Paldi',
            'password1': 'StrongPass123',
            'password2': 'StrongPass123',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        created_admin = User.objects.get(username='newadmin')
        self.assertEqual(created_admin.role, 'Admin')
        self.assertEqual(created_admin.assigned_area, 'Paldi')
        self.assertTrue(created_admin.is_staff)
        self.assertContains(response, 'created successfully')

    def test_non_superuser_cannot_open_create_admin_page(self):
        self.client.login(username='adminuser', password='password123')
        response = self.client.get(reverse('create_admin'))

        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_user_dashboard_has_google_maps_link_for_assignment(self):
        slot = ParkingSlot.objects.create(
            slot_number='TH-B1-88',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 88',
            status='Assigned',
        )
        SlotAssignment.objects.create(user=self.user, slot=slot, status='Active')

        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('user_dashboard'))

        self.assertContains(response, 'Open In Google Maps')
        self.assertContains(response, 'www.google.com/maps/search/')
        self.assertContains(response, 'Request Status Snapshot')
        self.assertContains(response, 'Most Used Parking Areas')

    def test_dashboard_free_counts_are_area_aware(self):
        paldi_b2_slot = ParkingSlot.objects.filter(area='Paldi', basement_level='B2').first()
        paldi_b2_slot.status = 'Assigned'
        paldi_b2_slot.save()

        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('user_dashboard'))

        self.assertContains(response, 'data-free-counts="Thaltej:8|Navrangpura:8|Paldi:7|Kalupur:8"')

    def test_chatbot_page_loads(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('chatbot'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ParkEase Assistant')

    def test_chatbot_answers_availability(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('chatbot_ask'), {'message': 'show parking availability'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('Thaltej', response.json()['reply'])

    def test_chatbot_blocks_out_of_scope_topics(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('chatbot_ask'), {'message': 'help me write python code'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['reply'],
            'I can help with ParkEase website questions and normal conversation only.',
        )

    @override_settings(GEMINI_API_KEY='test-key', GEMINI_CHATBOT_MODEL='gemini-2.5-flash-lite')
    @patch('accounts.views.get_gemini_chatbot_reply', return_value='Hello from ParkEase.')
    def test_chatbot_allows_normal_conversation_via_gemini(self, mocked_reply):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('chatbot_ask'), {'message': 'hello'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reply'], 'Hello from ParkEase.')
        mocked_reply.assert_called_once()

    def test_profile_can_store_additional_vehicle(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('profile'), {
            'action': 'add_vehicle',
            'nickname': 'Office SUV',
            'plate_number': 'gj02xy9876',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserVehicle.objects.filter(user=self.user, plate_number='GJ02XY9876').exists())

    def test_subscriptions_page_loads_for_user(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('subscriptions'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Free Pass')
        self.assertContains(response, 'Premium Pass')

    def test_subscription_verify_upgrades_user_pass(self):
        self.client.login(username='testuser', password='password123')
        with self.settings(RAZORPAY_KEY_ID='rzp_test_123', RAZORPAY_KEY_SECRET='secret_123'):
            token = build_subscription_callback_token(
                self.user.id,
                'Pro',
                'order_test_123',
            )
            body = 'order_test_123|pay_test_123'.encode('utf-8')
            signature = hmac.new(b'secret_123', body, hashlib.sha256).hexdigest()

            response = self.client.post(f"{reverse('subscription_verify', args=['Pro'])}?token={token}", {
                'razorpay_payment_id': 'pay_test_123',
                'razorpay_order_id': 'order_test_123',
                'razorpay_signature': signature,
            }, follow=True)

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.parking_pass, 'Pro')
        self.assertContains(response, 'Upgrade Complete')

    def test_subscription_verify_shows_cancelled_result_screen(self):
        self.client.login(username='testuser', password='password123')
        token = build_subscription_callback_token(
            self.user.id,
            'Pro',
            'order_test_123',
        )

        response = self.client.get(
            f"{reverse('subscription_verify', args=['Pro'])}?token={token}&status=cancelled"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Cancelled')
        self.assertContains(response, 'Try Razorpay Again')
