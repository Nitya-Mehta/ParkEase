import io
import hashlib
import hmac
from datetime import datetime, time
from decimal import Decimal
from unittest.mock import patch

from PIL import Image
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserVehicle
from .models import AutoBookingRule, ParkingSlot, ParkingRequest, SlotAssignment, VehicleScanLog

class ParkingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123',
            role='User',
            email='testuser@example.com',
            mobile_number='9999999999',
            vehicle_number='GJ01AB1234',
        )
        self.admin = User.objects.create_user(
            username='adminuser',
            password='password123',
            role='Admin',
            assigned_area='Thaltej',
        )
        self.slot = ParkingSlot.objects.create(
            slot_number='TH-B1-99',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 99',
            status='Free',
        )
        self.other_area_slot = ParkingSlot.objects.create(
            slot_number='PA-B1-50',
            area='Paldi',
            basement_level='B1',
            location='Paldi Basement -1 Bay 50',
            status='Free',
        )
        self.vip_slot = ParkingSlot.objects.create(
            slot_number='TH-B3-VIP4',
            area='Thaltej',
            basement_level='B3',
            location='Premium detailing zone',
            status='Free',
            vip_only=True,
        )
        self.today = timezone.localdate()

    def build_test_image(self, color=(255, 255, 255)):
        image = Image.new('RGB', (640, 360), color)
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG')
        return SimpleUploadedFile('vehicle.jpg', buffer.getvalue(), content_type='image/jpeg')

    def test_slot_creation(self):
        self.assertEqual(self.slot.status, 'Free')
        self.assertEqual(self.slot.area, 'Thaltej')

    def test_user_request_flow(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('confirm_parking_request', args=[self.slot.id]), {'booking_date': self.today.isoformat()})
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': self.today.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
        })
        self.assertEqual(ParkingRequest.objects.count(), 1)
        self.assertEqual(ParkingRequest.objects.first().status, 'Pending')
        self.assertEqual(ParkingRequest.objects.first().requested_slot, self.slot)
        
        # Trying to request again, should fail Business Logic rule (1 active request limit)
        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': self.today.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
        })
        self.assertRedirects(response, reverse('request_status'))
        self.assertEqual(ParkingRequest.objects.count(), 1) # Still 1

    def test_admin_assignment_flow(self):
        req = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )
        
        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('admin_assign_slot', args=[req.id]))

        self.assertEqual(SlotAssignment.objects.count(), 1)
        req.refresh_from_db()
        self.slot.refresh_from_db()
        
        self.assertEqual(req.status, 'Approved')
        self.assertEqual(self.slot.status, 'Assigned')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['testuser@example.com'])
        self.assertIn('approved', mail.outbox[0].subject.lower())
        
        # Another request for the same slot should handle slot status logic elegantly
        req2 = ParkingRequest.objects.create(
            user=User.objects.create_user(username='user2', password='123'),
            requested_slot=self.slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )
        response = self.client.post(reverse('admin_assign_slot', args=[req2.id]))
        self.assertRedirects(response, reverse('admin_pending_requests'))

    def test_user_sees_slot_request_confirmation(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': self.today.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
        }, follow=True)

        self.assertContains(response, 'Slot request sent')
        self.assertContains(response, 'request status page')

    def test_booking_page_has_location_map_and_switcher(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('submit_parking_request'))

        self.assertContains(response, 'data-switcher')
        self.assertContains(response, 'Satellite map of Ahmedabad')
        self.assertContains(response, 'data-area-target="Thaltej"')

    def test_area_scoped_admin_cannot_access_other_area_slot(self):
        self.client.login(username='adminuser', password='password123')
        response = self.client.get(reverse('admin_slot_edit', args=[self.other_area_slot.id]))
        self.assertEqual(response.status_code, 404)

    def test_user_can_cancel_pending_request(self):
        req = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('cancel_parking_request', args=[req.id]))
        self.assertRedirects(response, reverse('request_status'))
        req.refresh_from_db()
        self.assertEqual(req.status, 'Cancelled')

    def test_user_can_reschedule_pending_request(self):
        req = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )
        new_slot = ParkingSlot.objects.create(
            slot_number='TH-B1-100',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 100',
            status='Free',
        )

        self.client.login(username='testuser', password='password123')
        response = self.client.post(
            reverse('confirm_parking_request', args=[new_slot.id]) + f'?edit_request={req.id}',
            {'requested_start_time': self.today.isoformat(), 'edit_request': str(req.id), 'vehicle_plate_number': self.user.vehicle_number},
            follow=True,
        )

        req.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(req.status, 'Pending')
        self.assertEqual(req.requested_slot, new_slot)

    def test_user_rescheduling_approved_request_releases_old_assignment(self):
        approved_request = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Approved',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Active',
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            booked_end_time=timezone.make_aware(datetime.combine(self.today, time.max)),
        )
        self.slot.status = 'Assigned'
        self.slot.save(update_fields=['status'])
        new_slot = ParkingSlot.objects.create(
            slot_number='TH-B1-101',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 101',
            status='Free',
        )

        self.client.login(username='testuser', password='password123')
        response = self.client.post(
            reverse('confirm_parking_request', args=[new_slot.id]) + f'?edit_request={approved_request.id}',
            {'requested_start_time': self.today.isoformat(), 'edit_request': str(approved_request.id), 'vehicle_plate_number': self.user.vehicle_number},
            follow=True,
        )

        approved_request.refresh_from_db()
        assignment.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(approved_request.status, 'Pending')
        self.assertEqual(approved_request.requested_slot, new_slot)
        self.assertEqual(assignment.status, 'Released')
        self.assertEqual(self.slot.status, 'Free')

    def test_admin_can_delete_unassigned_slot(self):
        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('admin_slot_delete', args=[self.slot.id]))
        self.assertRedirects(response, reverse('admin_slot_list'))
        self.assertFalse(ParkingSlot.objects.filter(id=self.slot.id).exists())

    def test_admin_vehicle_scan_marks_assignment_inside(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Active',
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            vehicle_plate_number=self.user.vehicle_number,
        )
        self.client.login(username='adminuser', password='password123')

        response = self.client.post(reverse('admin_vehicle_scan'), {
            'image': self.build_test_image(),
            'plate_number': 'GJ01 AB 1234',
        }, follow=True)

        assignment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(assignment.entered_at)
        self.assertTrue(VehicleScanLog.objects.filter(status='authorized', matched_assignment=assignment).exists())

    def test_admin_vehicle_exit_scan_releases_assignment(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Active',
            entered_at=timezone.now() - timezone.timedelta(minutes=95),
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            vehicle_plate_number=self.user.vehicle_number,
        )
        self.slot.status = 'Assigned'
        self.slot.save(update_fields=['status'])
        self.client.login(username='adminuser', password='password123')

        response = self.client.post(reverse('admin_vehicle_scan'), {
            'gate_mode': 'exit',
            'image': self.build_test_image(),
            'plate_number': 'GJ01 AB 1234',
        })

        assignment.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertRedirects(response, reverse('admin_exit_payment', args=[assignment.id]), fetch_redirect_response=False)
        self.assertEqual(assignment.status, 'Released')
        self.assertIsNotNone(assignment.released_at)
        self.assertEqual(self.slot.status, 'Free')
        self.assertTrue(VehicleScanLog.objects.filter(status='exited', gate_mode='exit', matched_assignment=assignment).exists())
        self.assertEqual(assignment.parking_fee, Decimal('80.00'))

    def test_admin_vehicle_exit_scan_requires_vehicle_inside(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Active',
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            vehicle_plate_number=self.user.vehicle_number,
        )
        self.slot.status = 'Assigned'
        self.slot.save(update_fields=['status'])
        self.client.login(username='adminuser', password='password123')

        response = self.client.post(reverse('admin_vehicle_scan'), {
            'gate_mode': 'exit',
            'image': self.build_test_image(),
            'plate_number': 'GJ01 AB 1234',
        }, follow=True)

        assignment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(assignment.status, 'Active')
        self.assertIsNone(assignment.released_at)
        self.assertTrue(VehicleScanLog.objects.filter(status='already_outside', gate_mode='exit', matched_assignment=assignment).exists())

    def test_admin_exit_payment_creates_razorpay_order_context(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Released',
            entered_at=timezone.now() - timezone.timedelta(minutes=130),
            released_at=timezone.now(),
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
        )
        self.client.login(username='adminuser', password='password123')

        with patch('parking.views.create_razorpay_order', return_value={
            'id': 'order_test_123',
            'amount': 11000,
            'currency': 'INR',
        }):
            with self.settings(RAZORPAY_KEY_ID='rzp_test_123', RAZORPAY_KEY_SECRET='secret_123'):
                response = self.client.get(reverse('admin_exit_payment', args=[assignment.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'order_test_123')
        self.assertContains(response, 'Pay With Razorpay')
        self.assertEqual(self.client.session.get(f'razorpay_checkout_{assignment.id}')['order_id'], 'order_test_123')

    def test_verify_exit_payment_marks_payment_done_after_signature_check(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Released',
            entered_at=timezone.now() - timezone.timedelta(minutes=130),
            released_at=timezone.now(),
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
        )
        self.client.login(username='adminuser', password='password123')

        with self.settings(RAZORPAY_KEY_ID='rzp_test_123', RAZORPAY_KEY_SECRET='secret_123'):
            session = self.client.session
            session[f'razorpay_checkout_{assignment.id}'] = {'order_id': 'order_test_123'}
            session.save()

            body = 'order_test_123|pay_test_123'.encode('utf-8')
            signature = hmac.new(b'secret_123', body, hashlib.sha256).hexdigest()

            response = self.client.post(reverse('verify_exit_payment', args=[assignment.id]), {
                'razorpay_payment_id': 'pay_test_123',
                'razorpay_order_id': 'order_test_123',
                'razorpay_signature': signature,
            }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Successful')
        self.assertEqual(self.client.session.get(f'razorpay_payment_done_{assignment.id}'), True)

    def test_verify_exit_payment_redirects_back_on_gateway_failure(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Released',
            entered_at=timezone.now() - timezone.timedelta(minutes=90),
            released_at=timezone.now(),
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
        )
        self.client.login(username='adminuser', password='password123')

        with self.settings(RAZORPAY_KEY_ID='rzp_test_123', RAZORPAY_KEY_SECRET='secret_123'):
            session = self.client.session
            session[f'razorpay_checkout_{assignment.id}'] = {'order_id': 'order_test_123'}
            session.save()

            response = self.client.post(reverse('verify_exit_payment', args=[assignment.id]), {
                'error[code]': 'BAD_REQUEST_ERROR',
                'error[description]': 'Payment failed in mock flow.',
            }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Failed')
        self.assertContains(response, 'Try Razorpay Again')

    def test_verify_exit_payment_shows_cancelled_result_screen(self):
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Released',
            entered_at=timezone.now() - timezone.timedelta(minutes=90),
            released_at=timezone.now(),
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
        )
        self.client.login(username='adminuser', password='password123')

        response = self.client.get(
            reverse('verify_exit_payment', args=[assignment.id]) + '?status=cancelled'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Cancelled')
        self.assertContains(response, 'Try Razorpay Again')

    def test_parking_fee_uses_first_hour_plus_extra_hour_blocks(self):
        assignment = SlotAssignment(
            user=self.user,
            slot=self.slot,
            entered_at=timezone.now() - timezone.timedelta(minutes=125),
            released_at=timezone.now(),
        )

        self.assertEqual(assignment.parking_fee, Decimal('110.00'))

    def test_admin_assign_slot_redirects_when_request_is_no_longer_pending(self):
        req = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Approved',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
        )

        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('admin_assign_slot', args=[req.id]), follow=True)

        self.assertRedirects(response, reverse('admin_pending_requests'))
        self.assertContains(response, 'no longer pending approval')

    def test_free_pass_cannot_book_more_than_three_days_ahead(self):
        self.client.login(username='testuser', password='password123')
        far_date = self.today + timezone.timedelta(days=5)

        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': far_date.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'allows booking until')
        self.assertEqual(ParkingRequest.objects.count(), 0)

    def test_premium_pass_can_book_vip_slot(self):
        self.user.parking_pass = 'Premium'
        self.user.save(update_fields=['parking_pass'])
        self.client.login(username='testuser', password='password123')

        response = self.client.post(reverse('confirm_parking_request', args=[self.vip_slot.id]), {
            'requested_start_time': self.today.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
        })

        self.assertRedirects(response, reverse('request_status'))
        self.assertTrue(ParkingRequest.objects.filter(requested_slot=self.vip_slot).exists())

    def test_free_pass_is_blocked_from_vip_slot(self):
        self.client.login(username='testuser', password='password123')

        response = self.client.get(reverse('confirm_parking_request', args=[self.vip_slot.id]), {
            'booking_date': self.today.isoformat(),
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Premium Pass only')

    def test_pending_requests_show_premium_before_free(self):
        premium_user = User.objects.create_user(
            username='premium',
            password='password123',
            role='User',
            vehicle_number='GJ05AA0001',
            parking_pass='Premium',
        )
        premium_slot = ParkingSlot.objects.create(
            slot_number='TH-B1-77',
            area='Thaltej',
            basement_level='B1',
            location='Thaltej Basement -1 Bay 77',
            status='Free',
        )
        free_request = ParkingRequest.objects.create(
            user=self.user,
            requested_slot=self.slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
            vehicle_plate_number=self.user.vehicle_number,
        )
        premium_request = ParkingRequest.objects.create(
            user=premium_user,
            requested_slot=premium_slot,
            status='Pending',
            requested_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            duration_hours=24,
            vehicle_plate_number=premium_user.vehicle_number,
        )
        self.client.login(username='adminuser', password='password123')

        response = self.client.get(reverse('admin_pending_requests'))

        self.assertEqual(response.status_code, 200)
        requests = list(response.context['requests'])
        self.assertEqual(requests[0].id, premium_request.id)
        self.assertEqual(requests[1].id, free_request.id)

    def test_saved_vehicle_is_used_for_gate_scan_lookup(self):
        UserVehicle.objects.create(user=self.user, nickname='Second Car', plate_number='GJ02XY9876')
        assignment = SlotAssignment.objects.create(
            user=self.user,
            slot=self.slot,
            status='Active',
            booked_start_time=timezone.make_aware(datetime.combine(self.today, time.min)),
            vehicle_plate_number='GJ02XY9876',
        )
        self.client.login(username='adminuser', password='password123')

        response = self.client.post(reverse('admin_vehicle_scan'), {
            'image': self.build_test_image(),
            'plate_number': 'GJ02 XY 9876',
        }, follow=True)

        assignment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(assignment.entered_at)

    def test_pro_user_can_create_auto_booking_rule(self):
        self.user.parking_pass = 'Pro'
        self.user.save(update_fields=['parking_pass'])
        self.client.login(username='testuser', password='password123')

        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': self.today.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
            'enable_auto_book': 'on',
            'recurring_weekdays': ['0', '2', '4'],
            'recurring_end_date': (self.today + timezone.timedelta(days=14)).isoformat(),
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AutoBookingRule.objects.filter(user=self.user, requested_slot=self.slot, is_active=True).exists())

    def test_recurring_rule_locks_matching_future_dates_for_other_users(self):
        self.user.parking_pass = 'Pro'
        self.user.save(update_fields=['parking_pass'])
        other_user = User.objects.create_user(
            username='otheruser',
            password='password123',
            role='User',
            vehicle_number='GJ09AB4321',
        )
        start_date = self.today + timezone.timedelta(days=1)
        AutoBookingRule.objects.create(
            user=self.user,
            requested_slot=self.slot,
            vehicle_plate_number=self.user.vehicle_number,
            weekdays=str(start_date.weekday()),
            start_date=start_date,
            end_date=start_date + timezone.timedelta(days=14),
            is_active=True,
        )

        self.client.login(username='otheruser', password='password123')
        response = self.client.get(reverse('submit_parking_request'), {
            'booking_date': start_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Booked')

    def test_recurring_rule_cannot_exceed_one_month_ahead(self):
        self.user.parking_pass = 'Pro'
        self.user.save(update_fields=['parking_pass'])
        self.client.login(username='testuser', password='password123')
        start_date = self.today + timezone.timedelta(days=1)

        response = self.client.post(reverse('confirm_parking_request', args=[self.slot.id]), {
            'requested_start_time': start_date.isoformat(),
            'vehicle_plate_number': self.user.vehicle_number,
            'enable_auto_book': 'on',
            'recurring_weekdays': [str(start_date.weekday())],
            'recurring_end_date': (start_date + timezone.timedelta(days=45)).isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1 month ahead only')
