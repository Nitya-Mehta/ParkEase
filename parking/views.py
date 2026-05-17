from io import BytesIO
import base64
import hashlib
import hmac
import json
from decimal import Decimal, ROUND_UP
from datetime import datetime, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import qrcode
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from accounts.models import User, UserVehicle
from accounts.decorators import admin_required
from notifications import notification_channel_text, send_real_user_email
from .anpr import build_content_file, decode_scan_image, detect_plate_region, normalize_plate_text
from .models import AutoBookingRule, ParkingRequest, ParkingSlot, SlotAssignment, VehicleScanLog
from .forms import AdminVehicleScanForm, ParkingRequestForm, ParkingSlotForm
from .location_data import AHMEDABAD_SATELLITE_MAP_URL, parking_locations_for_template

AREA_OPTIONS = [choice[0] for choice in ParkingSlot.AREA_CHOICES]
BASEMENT_OPTIONS = [choice[0] for choice in ParkingSlot.BASEMENT_CHOICES]
BOOKING_RATE_PER_HOUR = Decimal('40.00')
OVERSTAY_RATE_PER_HOUR = Decimal('75.00')


def razorpay_checkout_session_key(assignment_id):
    return f'razorpay_checkout_{assignment_id}'


def razorpay_payment_done_session_key(assignment_id):
    return f'razorpay_payment_done_{assignment_id}'


def razorpay_credentials():
    return settings.RAZORPAY_KEY_ID.strip(), settings.RAZORPAY_KEY_SECRET.strip()


def razorpay_is_configured():
    key_id, key_secret = razorpay_credentials()
    return bool(key_id and key_secret)


def create_razorpay_order(amount_paise, receipt, notes=None):
    key_id, key_secret = razorpay_credentials()
    auth_token = base64.b64encode(f'{key_id}:{key_secret}'.encode('utf-8')).decode('ascii')
    payload = json.dumps({
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': receipt,
        'notes': notes or {},
    }).encode('utf-8')
    request = Request(
        'https://api.razorpay.com/v1/orders',
        data=payload,
        headers={
            'Authorization': f'Basic {auth_token}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise ValueError(f'Razorpay order creation failed: {detail or exc.reason}') from exc
    except URLError as exc:
        raise ValueError(f'Razorpay is unreachable right now: {exc.reason}') from exc


def verify_razorpay_payment_signature(order_id, payment_id, signature):
    _, key_secret = razorpay_credentials()
    body = f'{order_id}|{payment_id}'.encode('utf-8')
    expected = hmac.new(key_secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_assignment_payment_amount(assignment):
    amount = assignment.total_amount or assignment.parking_fee or Decimal('0.00')
    return amount.quantize(Decimal('0.01'))


def get_admin_scope_area(user):
    if user.role == 'Admin' and user.assigned_area:
        return user.assigned_area
    return None


def get_selected_area(request, allowed_area=None):
    if allowed_area:
        return allowed_area
    selected_area = request.GET.get('area', AREA_OPTIONS[0])
    if selected_area not in AREA_OPTIONS:
        return AREA_OPTIONS[0]
    return selected_area


def get_selected_level(request):
    selected_level = request.GET.get('level', BASEMENT_OPTIONS[0])
    if selected_level not in BASEMENT_OPTIONS:
        return BASEMENT_OPTIONS[0]
    return selected_level


def user_vehicle_choices(user):
    choices = []
    for index, plate_number in enumerate(user.saved_vehicle_numbers):
        label = plate_number
        if index == 0:
            label = f'{plate_number} (Primary)'
        choices.append((plate_number, label))
    return choices


def slot_is_accessible_for_user(user, slot):
    return user.can_book_vip_slots or not slot.is_vip


def slot_access_reason(user, slot):
    if slot_is_accessible_for_user(user, slot):
        return ''
    return 'Premium Pass required'


def booking_window_max_date(user):
    return timezone.localdate() + timezone.timedelta(days=user.booking_window_days)


def next_matching_rule_date(rule, from_date=None):
    current_date = max(from_date or timezone.localdate(), rule.start_date)
    if rule.last_generated_date and current_date <= rule.last_generated_date:
        current_date = rule.last_generated_date + timezone.timedelta(days=1)

    while current_date <= rule.end_date:
        if current_date.weekday() in rule.weekday_numbers:
            return current_date
        current_date += timezone.timedelta(days=1)
    return None


def sync_auto_booking_rule(rule):
    user = rule.user
    if not rule.is_active or not user.can_use_auto_booking:
        if rule.is_active and not user.can_use_auto_booking:
            rule.is_active = False
            rule.save(update_fields=['is_active', 'updated_at'])
        return None

    if not rule.requested_slot.is_active or not slot_is_accessible_for_user(user, rule.requested_slot):
        return None

    if ParkingRequest.objects.filter(user=user, status='Pending').exists():
        return None

    if SlotAssignment.objects.filter(user=user, status='Active').exists():
        return None

    candidate_date = next_matching_rule_date(rule)
    if not candidate_date:
        return None

    if candidate_date > booking_window_max_date(user):
        return None

    if rule.requested_slot_id in reserved_slot_ids_for_date(candidate_date, exclude_rule_id=rule.id):
        return None

    parking_request = ParkingRequest.objects.create(
        user=user,
        requested_slot=rule.requested_slot,
        status='Pending',
        requested_start_time=booking_day_start(candidate_date),
        duration_hours=24,
        vehicle_plate_number=rule.vehicle_plate_number,
        is_auto_booked=True,
    )
    rule.last_generated_date = candidate_date
    rule.save(update_fields=['last_generated_date', 'updated_at'])
    return parking_request


def sync_auto_booking_rules(rules=None, user=None):
    rules = rules or AutoBookingRule.objects.filter(is_active=True).select_related('user', 'requested_slot')
    if user is not None:
        rules = rules.filter(user=user)
    created_requests = []
    for rule in rules:
        request_obj = sync_auto_booking_rule(rule)
        if request_obj is not None:
            created_requests.append(request_obj)
    return created_requests


def slot_queryset_for_admin(request):
    queryset = ParkingSlot.objects.all()
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        queryset = queryset.filter(area=scope_area)
    return queryset


def live_slot_payload(queryset=None):
    queryset = queryset if queryset is not None else ParkingSlot.objects.all()
    slots = list(queryset.order_by('area', 'basement_level', 'slot_number'))
    return {
        'slots': [
            {
                'id': slot.id,
                'area': slot.area,
                'level': slot.basement_level,
                'slot_number': slot.slot_number,
                'status': slot.status,
                'is_active': slot.is_active,
            }
            for slot in slots
        ],
        'summaries': {
            f'{area}:{level}': queryset.filter(
                area=area,
                basement_level=level,
                status='Free',
                is_active=True,
            ).count()
            for area in AREA_OPTIONS
            for level in BASEMENT_OPTIONS
        },
    }


@login_required
def live_slot_status(request):
    return JsonResponse(live_slot_payload())


@admin_required
def admin_vehicle_scan(request):
    scope_area = get_admin_scope_area(request.user)
    form = AdminVehicleScanForm(request.POST or None, request.FILES or None)
    result = None
    latest_scans = VehicleScanLog.objects.select_related('matched_user', 'matched_assignment__slot').order_by('-created_at')[:6]

    if request.method == 'POST' and form.is_valid():
        gate_mode = form.cleaned_data.get('gate_mode') or 'entry'
        image_bytes, filename = decode_scan_image(
            uploaded_file=form.cleaned_data.get('image'),
            captured_image_data=form.cleaned_data.get('captured_image_data', ''),
        )
        user_lookup = vehicle_user_lookup()
        manual_plate_number = normalize_plate_text(form.cleaned_data.get('plate_number'))
        detection = detect_plate_region(image_bytes, expected_plates=set(user_lookup.keys())) if image_bytes else None

        if not image_bytes:
            messages.error(request, 'The camera image could not be processed. Please try again.')
            return redirect('admin_vehicle_scan')

        plate_number = detection.get('plate_text') if detection else ''
        plate_source = 'ocr' if plate_number else ''
        if manual_plate_number and (not plate_number or (manual_plate_number in user_lookup and plate_number not in user_lookup)):
            plate_number = manual_plate_number
            plate_source = 'manual'

        matched_user = None
        matched_assignment = None
        status = 'unreadable'
        notes = 'Plate number could not be confirmed.'

        if plate_number:
            if gate_mode == 'exit':
                matched_user = (user_lookup or vehicle_user_lookup()).get(normalize_plate_text(plate_number))
                if matched_user:
                    matched_assignment = latest_active_assignment_for_user(matched_user, scope_area=scope_area)
                if matched_assignment and matched_assignment.entered_at:
                    matched_assignment.released_at = timezone.now()
                    matched_assignment.status = 'Released'
                    matched_assignment.overstay_amount = Decimal('0.00')
                    matched_assignment.save(update_fields=['released_at', 'status', 'overstay_amount'])
                    matched_assignment.slot.status = 'Free'
                    matched_assignment.slot.save(update_fields=['status'])
                    status = 'exited'
                    notes = f'Vehicle {plate_number} checked out successfully from slot {matched_assignment.slot.slot_number}.'
                elif matched_assignment:
                    status = 'already_outside'
                    notes = f'Vehicle {plate_number} has an active booking for slot {matched_assignment.slot.slot_number} but is not marked inside yet.'
                elif matched_user:
                    status = 'no_booking'
                    notes = f'Vehicle {plate_number} is registered but has no active slot assignment to release.'
                else:
                    status = 'unregistered'
                    notes = f'No ParkEase account was found for vehicle {plate_number}.'
            else:
                matched_user, matched_assignment = active_assignment_for_plate(
                    plate_number,
                    scope_area=scope_area,
                    user_lookup=user_lookup,
                )
                if matched_assignment and matched_assignment.entered_at:
                    status = 'already_inside'
                    notes = f'Vehicle {plate_number} is already marked inside.'
                elif matched_assignment:
                    matched_assignment.entered_at = timezone.now()
                    matched_assignment.slot.status = 'Assigned'
                    matched_assignment.slot.save(update_fields=['status'])
                    matched_assignment.save(update_fields=['entered_at'])
                    status = 'authorized'
                    notes = f'Vehicle {plate_number} is verified and marked inside slot {matched_assignment.slot.slot_number}.'
                elif matched_user:
                    status = 'no_booking'
                    notes = f'Vehicle {plate_number} is registered but has no valid booking for today.'
                else:
                    status = 'unregistered'
                    notes = f'No ParkEase account was found for vehicle {plate_number}.'
        elif manual_plate_number:
            notes = f'OCR could not read the plate clearly. Manual input {manual_plate_number} was provided but did not match a valid booking.'

        scan_log = VehicleScanLog.objects.create(
            source='camera' if form.cleaned_data.get('captured_image_data') else 'upload',
            gate_mode=gate_mode,
            status=status,
            scan_image=build_content_file(image_bytes, filename),
            detected_plate=plate_number,
            bounding_box=(detection or {}).get('bounding_box') or {},
            matched_user=matched_user,
            matched_assignment=matched_assignment,
            notes=notes,
        )
        latest_scans = VehicleScanLog.objects.select_related('matched_user', 'matched_assignment__slot').order_by('-created_at')[:6]
        result = {
            'log': scan_log,
            'detection': detection,
            'matched_user': matched_user,
            'matched_assignment': matched_assignment,
            'plate_number': plate_number,
            'plate_source': plate_source or 'unreadable',
            'status': status,
            'notes': notes,
            'gate_mode': gate_mode,
        }

        if status == 'exited' and matched_assignment:
            request.session[f'dummy_payment_pending_{matched_assignment.id}'] = {
                'plate_number': plate_number,
                'scan_log_id': scan_log.id,
            }
            messages.success(request, 'Vehicle exit verified. Continue to payment.')
            return redirect('admin_exit_payment', assignment_id=matched_assignment.id)

        if status == 'authorized':
            messages.success(request, 'Vehicle verified and marked inside.')
        elif status == 'exited':
            messages.success(request, 'Vehicle verified and checked out successfully.')
        elif status == 'already_inside':
            messages.info(request, 'Vehicle is already marked inside.')
        elif status == 'already_outside':
            messages.info(request, 'Vehicle is not marked inside yet, so it cannot be checked out.')
        else:
            messages.warning(request, 'Scan completed. Please review the result.')

    return render(request, 'parking/admin_vehicle_scan.html', {
        'form': form,
        'result': result,
        'latest_scans': latest_scans,
        'admin_scope_area': scope_area,
    })


@admin_required
def admin_exit_payment(request, assignment_id):
    assignments = SlotAssignment.objects.select_related('user', 'slot')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    assignment = get_object_or_404(assignments, id=assignment_id, status='Released')
    payment_state = request.session.get(f'dummy_payment_pending_{assignment.id}', {})
    payment_done = request.session.get(razorpay_payment_done_session_key(assignment.id), False)
    checkout_state = request.session.get(razorpay_checkout_session_key(assignment.id), {})
    amount = get_assignment_payment_amount(assignment)
    amount_paise = int(amount * 100)
    gateway_ready = razorpay_is_configured()

    if not payment_done and gateway_ready and not checkout_state.get('order_id'):
        try:
            order = create_razorpay_order(
                amount_paise=amount_paise,
                receipt=f'parkease-exit-{assignment.id}-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                notes={
                    'assignment_id': str(assignment.id),
                    'slot_number': assignment.slot.slot_number,
                    'vehicle_number': payment_state.get('plate_number') or assignment.vehicle_plate_number or assignment.user.vehicle_number or '',
                },
            )
            checkout_state = {
                'order_id': order.get('id', ''),
                'amount_paise': order.get('amount', amount_paise),
                'currency': order.get('currency', 'INR'),
            }
            request.session[razorpay_checkout_session_key(assignment.id)] = checkout_state
        except ValueError as exc:
            gateway_ready = False
            messages.error(request, str(exc))

    if not gateway_ready and not payment_done:
        messages.warning(
            request,
            'Razorpay is not ready yet. Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in the project .env file.',
        )

    return render(request, 'parking/admin_exit_payment.html', {
        'assignment': assignment,
        'payment_done': payment_done,
        'payment_state': payment_state,
        'payment_amount': amount,
        'checkout_state': checkout_state,
        'gateway_ready': gateway_ready and bool(checkout_state.get('order_id')),
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'razorpay_company_name': settings.RAZORPAY_COMPANY_NAME,
        'razorpay_callback_url': request.build_absolute_uri(
            reverse('verify_exit_payment', args=[assignment.id])
        ),
    })


@admin_required
@csrf_exempt
def verify_exit_payment(request, assignment_id):
    assignments = SlotAssignment.objects.select_related('user', 'slot')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    assignment = get_object_or_404(assignments, id=assignment_id, status='Released')

    if request.method != 'POST':
        checkout_status = request.GET.get('status', '').strip().lower()
        if checkout_status == 'cancelled':
            return render(request, 'parking/exit_payment_result.html', {
                'success': False,
                'title': 'Payment Cancelled',
                'message': f'The Razorpay checkout for slot {assignment.slot.slot_number} was cancelled before payment was completed.',
                'return_url': reverse('admin_exit_payment', args=[assignment.id]),
                'return_label': 'Try Razorpay Again',
            })
        if checkout_status == 'failed':
            failure_reason = request.GET.get('reason', '').strip() or 'Razorpay reported that the payment failed.'
            return render(request, 'parking/exit_payment_result.html', {
                'success': False,
                'title': 'Payment Failed',
                'message': failure_reason,
                'return_url': reverse('admin_exit_payment', args=[assignment.id]),
                'return_label': 'Try Razorpay Again',
            })
        return redirect('admin_exit_payment', assignment_id=assignment_id)

    if not razorpay_is_configured():
        messages.error(request, 'Razorpay keys are missing. Configure them before verifying payments.')
        return redirect('admin_exit_payment', assignment_id=assignment.id)

    checkout_state = request.session.get(razorpay_checkout_session_key(assignment.id), {})
    payment_id = request.POST.get('razorpay_payment_id', '').strip()
    order_id = request.POST.get('razorpay_order_id', '').strip()
    signature = request.POST.get('razorpay_signature', '').strip()
    error_code = request.POST.get('error[code]', '').strip()
    error_description = request.POST.get('error[description]', '').strip()

    if error_code or error_description:
        return render(request, 'parking/exit_payment_result.html', {
            'success': False,
            'title': 'Payment Failed',
            'message': f'Razorpay reported a failed payment: {error_description or error_code}.',
            'return_url': reverse('admin_exit_payment', args=[assignment.id]),
            'return_label': 'Try Razorpay Again',
        })

    if not payment_id or not order_id or not signature:
        return render(request, 'parking/exit_payment_result.html', {
            'success': False,
            'title': 'Payment Incomplete',
            'message': 'Payment was not completed in Razorpay.',
            'return_url': reverse('admin_exit_payment', args=[assignment.id]),
            'return_label': 'Try Razorpay Again',
        })

    expected_order_id = checkout_state.get('order_id')
    if expected_order_id and expected_order_id != order_id:
        return render(request, 'parking/exit_payment_result.html', {
            'success': False,
            'title': 'Payment Verification Failed',
            'message': 'The returned Razorpay order did not match this checkout.',
            'return_url': reverse('admin_exit_payment', args=[assignment.id]),
            'return_label': 'Try Razorpay Again',
        })

    if not verify_razorpay_payment_signature(order_id, payment_id, signature):
        return render(request, 'parking/exit_payment_result.html', {
            'success': False,
            'title': 'Payment Verification Failed',
            'message': 'Razorpay payment verification failed.',
            'return_url': reverse('admin_exit_payment', args=[assignment.id]),
            'return_label': 'Try Razorpay Again',
        })

    request.session[razorpay_payment_done_session_key(assignment.id)] = True
    request.session[razorpay_checkout_session_key(assignment.id)] = {
        **checkout_state,
        'payment_id': payment_id,
        'signature': signature,
    }
    return render(request, 'parking/exit_payment_result.html', {
        'success': True,
        'title': 'Payment Successful',
        'message': f'Razorpay verified the payment for slot {assignment.slot.slot_number}.',
        'return_url': reverse('admin_vehicle_scan'),
        'return_label': 'Back To Gate Scan',
    })


def build_assignment_qr_token(assignment):
    return signing.dumps(
        {'assignment_id': assignment.id, 'slot_id': assignment.slot_id, 'user_id': assignment.user_id},
        salt='parkease-assignment-qr',
    )


def build_assignment_qr_image(validation_url):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(validation_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def compute_booked_amount(duration_hours):
    return (BOOKING_RATE_PER_HOUR * Decimal(duration_hours)).quantize(Decimal('0.01'))


def compute_overstay_amount(end_time, released_at=None):
    if not end_time:
        return Decimal('0.00'), 0
    comparison_time = released_at or timezone.now()
    if comparison_time <= end_time:
        return Decimal('0.00'), 0
    overtime_minutes = int((comparison_time - end_time).total_seconds() // 60)
    overtime_hours = (Decimal(overtime_minutes) / Decimal(60)).quantize(Decimal('1'), rounding=ROUND_UP)
    return (overtime_hours * OVERSTAY_RATE_PER_HOUR).quantize(Decimal('0.01')), overtime_minutes


def get_selected_booking_date(request):
    raw_value = request.GET.get('booking_date') or request.POST.get('booking_date')
    if raw_value:
        try:
            parsed = datetime.strptime(raw_value, '%Y-%m-%d').date()
            if parsed >= timezone.localdate():
                return parsed
        except ValueError:
            pass
    return timezone.localdate()


def booking_day_start(selected_date):
    naive = datetime.combine(selected_date, time.min)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def auto_booking_rule_matches_date(rule, selected_date):
    if not rule.is_active:
        return False
    if selected_date < rule.start_date or selected_date > rule.end_date:
        return False
    return selected_date.weekday() in rule.weekday_numbers


def reserved_slot_ids_for_date(selected_date, exclude_request_id=None, exclude_assignment_id=None, exclude_rule_id=None):
    request_queryset = ParkingRequest.objects.filter(
        status='Pending',
        requested_slot__isnull=False,
        requested_start_time__date=selected_date,
    )
    if exclude_request_id:
        request_queryset = request_queryset.exclude(id=exclude_request_id)
    assignment_queryset = SlotAssignment.objects.filter(
        status='Active',
    ).filter(
        Q(booked_start_time__date=selected_date) | Q(booked_start_time__isnull=True, assigned_at__date=selected_date)
    )
    if exclude_assignment_id:
        assignment_queryset = assignment_queryset.exclude(id=exclude_assignment_id)
    auto_booking_queryset = AutoBookingRule.objects.filter(
        is_active=True,
        requested_slot__isnull=False,
        start_date__lte=selected_date,
        end_date__gte=selected_date,
    ).select_related('requested_slot')
    if exclude_rule_id:
        auto_booking_queryset = auto_booking_queryset.exclude(id=exclude_rule_id)

    return set(
        request_queryset.values_list('requested_slot_id', flat=True)
    ) | set(
        assignment_queryset.values_list('slot_id', flat=True)
    ) | {
        rule.requested_slot_id
        for rule in auto_booking_queryset
        if auto_booking_rule_matches_date(rule, selected_date)
    }


def editable_request_for_user(user, request_id):
    return get_object_or_404(
        ParkingRequest.objects.select_related('requested_slot'),
        id=request_id,
        user=user,
        status__in=['Pending', 'Approved'],
    )


def vehicle_user_lookup():
    lookup = {}
    users = User.objects.all().prefetch_related('saved_vehicles')
    for user in users:
        for plate_number in user.saved_vehicle_numbers:
            normalized = normalize_plate_text(plate_number)
            if normalized:
                lookup[normalized] = user
    return lookup


def active_assignment_for_plate(plate_number, scope_area=None, user_lookup=None):
    normalized_plate = normalize_plate_text(plate_number)
    if not normalized_plate:
        return None, None

    user = (user_lookup or vehicle_user_lookup()).get(normalized_plate)
    if not user:
        return None, None

    assignments = SlotAssignment.objects.filter(user=user, status='Active').select_related('slot', 'user')
    direct_vehicle_assignments = assignments.filter(vehicle_plate_number=normalized_plate)
    if direct_vehicle_assignments.exists():
        assignments = direct_vehicle_assignments
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)

    today = timezone.localdate()
    assignment = assignments.filter(booked_start_time__date=today).order_by('assigned_at').first()
    if not assignment:
        assignment = assignments.filter(booked_start_time__isnull=True, assigned_at__date=today).order_by('assigned_at').first()
    return user, assignment


def latest_active_assignment_for_user(user, scope_area=None):
    assignments = SlotAssignment.objects.filter(user=user, status='Active').select_related('slot', 'user')
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    return assignments.order_by('-booked_start_time', '-assigned_at').first()


def annotate_slot_presence(slots, scope_area=None):
    assignments = SlotAssignment.objects.filter(status='Active').select_related('slot')
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    active_assignments = list(assignments)
    inside_slot_ids = {assignment.slot_id for assignment in active_assignments if assignment.entered_at}
    assigned_slot_ids = {assignment.slot_id for assignment in active_assignments}

    for slot in slots:
        if not slot.is_active:
            slot.dashboard_presence = 'Disabled'
        elif slot.id in inside_slot_ids:
            slot.dashboard_presence = 'Inside'
        elif slot.id in assigned_slot_ids or slot.status == 'Assigned':
            slot.dashboard_presence = 'Outside'
        else:
            slot.dashboard_presence = 'Free'
    return slots


@admin_required
def admin_slot_list(request):
    scope_area = get_admin_scope_area(request.user)
    selected_area = get_selected_area(request, allowed_area=scope_area)
    selected_level = get_selected_level(request)
    base_queryset = slot_queryset_for_admin(request)
    slots = list(base_queryset.filter(
        area=selected_area,
        basement_level=selected_level,
    ).order_by('slot_number'))
    annotate_slot_presence(slots, scope_area=scope_area)

    panel_areas = [scope_area] if scope_area else AREA_OPTIONS
    slot_panels = build_slot_panels(panel_areas, base_queryset)
    for area_panel in slot_panels:
        for level_panel in area_panel['levels']:
            annotate_slot_presence(level_panel['slots'], scope_area=scope_area)

    return render(request, 'parking/admin_slot_list.html', {
        'slots': slots,
        'selected_area': selected_area,
        'selected_level': selected_level,
        'selected_level_label': dict(ParkingSlot.BASEMENT_CHOICES).get(selected_level, selected_level),
        'area_options': panel_areas,
        'admin_scope_area': scope_area,
        'basement_summaries': build_basement_summaries(selected_area, base_queryset, panel_areas),
        'slot_panels': slot_panels,
    })

@admin_required
def admin_slot_create(request):
    scope_area = get_admin_scope_area(request.user)
    if request.method == 'POST':
        form = ParkingSlotForm(request.POST, locked_area=scope_area)
        if form.is_valid():
            slot = form.save(commit=False)
            if scope_area:
                slot.area = scope_area
            slot.save()
            messages.success(request, 'Parking slot created successfully.')
            return redirect('admin_slot_list')
    else:
        form = ParkingSlotForm(locked_area=scope_area)
    return render(request, 'parking/admin_slot_form.html', {'form': form, 'title': 'Create Parking Slot'})

@admin_required
def admin_slot_edit(request, slot_id):
    slot = get_object_or_404(slot_queryset_for_admin(request), id=slot_id)
    scope_area = get_admin_scope_area(request.user)
    if request.method == 'POST':
        form = ParkingSlotForm(request.POST, instance=slot, locked_area=scope_area)
        if form.is_valid():
            slot = form.save(commit=False)
            if scope_area:
                slot.area = scope_area
            slot.save()
            messages.success(request, 'Parking slot updated successfully.')
            return redirect('admin_slot_list')
    else:
        form = ParkingSlotForm(instance=slot, locked_area=scope_area)
    return render(request, 'parking/admin_slot_form.html', {'form': form, 'title': f'Edit Slot {slot.slot_number}'})

@admin_required
def admin_slot_toggle_active(request, slot_id):
    slot = get_object_or_404(slot_queryset_for_admin(request), id=slot_id)
    slot.is_active = not slot.is_active
    slot.save()
    status_text = "enabled" if slot.is_active else "disabled"
    messages.success(request, f'Slot {slot.slot_number} has been {status_text}.')
    return redirect('admin_slot_list')

@admin_required
def admin_slot_delete(request, slot_id):
    slot = get_object_or_404(slot_queryset_for_admin(request), id=slot_id)
    if request.method == 'POST':
        if SlotAssignment.objects.filter(slot=slot, status='Active').exists():
            messages.error(request, 'Assigned slots must be released before deletion.')
            return redirect('admin_slot_list')
        slot_number = slot.slot_number
        slot.delete()
        messages.success(request, f'Slot {slot_number} has been deleted.')
    return redirect('admin_slot_list')

@admin_required
def admin_slot_force_release(request, slot_id):
    slot = get_object_or_404(slot_queryset_for_admin(request), id=slot_id)
    if request.method == 'POST' and slot.status == 'Assigned':
        assignment = SlotAssignment.objects.filter(slot=slot, status='Active').first()
        if assignment:
            assignment.status = 'Released'
            assignment.released_at = timezone.now()
            assignment.overstay_amount = Decimal('0.00')
            assignment.save()
        
        # Free the slot
        slot.status = 'Free'
        slot.save()
        messages.success(request, f'Slot {slot.slot_number} has been forcefully freed.')
    return redirect('admin_slot_list')

from accounts.decorators import user_required


def build_basement_summaries(area, queryset=None, area_options=None):
    base_queryset = queryset if queryset is not None else ParkingSlot.objects.all()
    area_options = area_options or AREA_OPTIONS
    summaries = []
    for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
        total_slots = base_queryset.filter(
            area=area,
            basement_level=basement_value,
            is_active=True,
        ).count()
        free_slots = base_queryset.filter(
            area=area,
            basement_level=basement_value,
            status='Free',
            is_active=True,
        ).count()
        free_counts = {
            option: base_queryset.filter(
                area=option,
                basement_level=basement_value,
                status='Free',
                is_active=True,
            ).count()
            for option in area_options
        }
        summaries.append({
            'value': basement_value,
            'label': basement_label,
            'total_slots': total_slots,
            'free_slots': free_slots,
            'free_counts_text': '|'.join(f'{option}:{count}' for option, count in free_counts.items()),
        })
    return summaries


def build_slot_panels(area_options, queryset):
    panels = []
    for area in area_options:
        levels = []
        for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
            levels.append({
                'value': basement_value,
                'label': basement_label,
                'slots': list(queryset.filter(area=area, basement_level=basement_value).order_by('slot_number')),
            })
        panels.append({
            'area': area,
            'levels': levels,
        })
    return panels


def build_slot_panels_from_slots(area_options, slots):
    panels = []
    for area in area_options:
        area_slots = [slot for slot in slots if slot.area == area]
        levels = []
        for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
            levels.append({
                'value': basement_value,
                'label': basement_label,
                'slots': [slot for slot in area_slots if slot.basement_level == basement_value],
            })
        panels.append({
            'area': area,
            'levels': levels,
        })
    return panels

@user_required
def submit_parking_request(request):
    edit_request_id = request.GET.get('edit_request')
    editable_request = editable_request_for_user(request.user, edit_request_id) if edit_request_id else None

    # Check if user already has a pending request
    has_pending = ParkingRequest.objects.filter(user=request.user, status='Pending').exclude(
        id=getattr(editable_request, 'id', None)
    ).exists()
    # Check if user already has an active assignment
    has_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').exists()
    
    if has_pending or (has_assignment and not editable_request):
        messages.warning(request, "You already have an active parking request or assignment.")
        return redirect('request_status')

    selected_area = get_selected_area(request)
    selected_level = get_selected_level(request)
    selected_booking_date = get_selected_booking_date(request)
    if not request.user.can_book_date(selected_booking_date):
        capped_date = booking_window_max_date(request.user)
        messages.info(
            request,
            f'{request.user.parking_pass_label} users can book until {capped_date.strftime("%d %b %Y")}. Showing that date instead.',
        )
        selected_booking_date = capped_date
    selected_spot_id = request.GET.get('slot')
    active_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first() if editable_request else None
    if editable_request and not selected_spot_id and editable_request.requested_slot_id:
        selected_spot_id = str(editable_request.requested_slot_id)
    if editable_request and 'booking_date' not in request.GET and editable_request.requested_start_time:
        selected_booking_date = timezone.localtime(editable_request.requested_start_time).date()
    reserved_slot_ids = reserved_slot_ids_for_date(
        selected_booking_date,
        exclude_request_id=getattr(editable_request, 'id', None),
        exclude_assignment_id=getattr(active_assignment, 'id', None) if editable_request else None,
    )

    all_slots = list(ParkingSlot.objects.filter(is_active=True).order_by('area', 'basement_level', 'slot_number'))
    preselected_slot = None
    for slot in all_slots:
        slot.is_accessible = slot_is_accessible_for_user(request.user, slot)
        slot.lock_reason = slot_access_reason(request.user, slot)
        slot.display_status = 'Assigned' if slot.id in reserved_slot_ids else ('Locked' if not slot.is_accessible else 'Free')
        slot.is_preselected = selected_spot_id == str(slot.id) and slot.display_status == 'Free'
        if slot.is_preselected:
            preselected_slot = slot
    grouped_slots = build_slot_panels_from_slots(AREA_OPTIONS, all_slots)

    basement_summaries = []
    for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
        free_counts = {}
        for area in AREA_OPTIONS:
            free_counts[area] = sum(
                1
                for slot in all_slots
                if slot.area == area and slot.basement_level == basement_value and slot.display_status == 'Free'
            )
        basement_summaries.append({
            'value': basement_value,
            'label': basement_label,
            'free_slots': free_counts.get(selected_area, 0),
            'free_counts_text': '|'.join(f'{option}:{count}' for option, count in free_counts.items()),
        })
    selected_level_label = dict(ParkingSlot.BASEMENT_CHOICES).get(selected_level, selected_level)

    return render(request, 'parking/request_submit.html', {
        'area_options': AREA_OPTIONS,
        'editable_request': editable_request,
        'selected_area': selected_area,
        'selected_level': selected_level,
        'selected_level_label': selected_level_label,
        'parking_locations': parking_locations_for_template(AREA_OPTIONS),
        'satellite_map_url': AHMEDABAD_SATELLITE_MAP_URL,
        'grouped_slots': grouped_slots,
        'basement_summaries': basement_summaries,
        'selected_booking_date': selected_booking_date,
        'preselected_slot': preselected_slot,
        'booking_window_max_date': booking_window_max_date(request.user),
    })


@user_required
def confirm_parking_request(request, slot_id):
    edit_request_id = request.GET.get('edit_request') or request.POST.get('edit_request')
    editable_request = editable_request_for_user(request.user, edit_request_id) if edit_request_id else None

    has_pending = ParkingRequest.objects.filter(user=request.user, status='Pending').exclude(
        id=getattr(editable_request, 'id', None)
    ).exists()
    has_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').exists()

    if has_pending or (has_assignment and not editable_request):
        messages.warning(request, "You already have an active parking request or assignment.")
        return redirect('request_status')

    selected_booking_date = get_selected_booking_date(request)
    requested_slot = get_object_or_404(
        ParkingSlot,
        id=slot_id,
        is_active=True,
    )
    if not slot_is_accessible_for_user(request.user, requested_slot):
        messages.error(request, 'This VIP slot is available on the Premium Pass only.')
        return redirect(
            f"{reverse('submit_parking_request')}?area={requested_slot.area}&level={requested_slot.basement_level}&booking_date={selected_booking_date.isoformat()}"
        )
    active_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first() if editable_request else None

    if request.method == 'POST':
        form = ParkingRequestForm(request.POST, user=request.user)
        if form.is_valid():
            selected_booking_date = form.cleaned_data['requested_start_time']
            vehicle_plate_number = form.cleaned_data['vehicle_plate_number']
            if requested_slot.id in reserved_slot_ids_for_date(
                selected_booking_date,
                exclude_request_id=getattr(editable_request, 'id', None),
                exclude_assignment_id=getattr(active_assignment, 'id', None) if editable_request else None,
            ):
                messages.error(request, 'This slot is already reserved for the selected date.')
                edit_query = f'&edit_request={editable_request.id}' if editable_request else ''
                return redirect(
                    f"{reverse('submit_parking_request')}?area={requested_slot.area}&level={requested_slot.basement_level}&booking_date={selected_booking_date.isoformat()}{edit_query}"
                )
            if editable_request:
                if editable_request.status == 'Approved' and active_assignment:
                    active_assignment.status = 'Released'
                    active_assignment.released_at = timezone.now()
                    active_assignment.overstay_amount = Decimal('0.00')
                    active_assignment.save()

                    previous_slot = active_assignment.slot
                    previous_slot.status = 'Free'
                    previous_slot.save(update_fields=['status'])

                editable_request.requested_slot = requested_slot
                editable_request.status = 'Pending'
                editable_request.requested_start_time = booking_day_start(selected_booking_date)
                editable_request.duration_hours = 24
                editable_request.vehicle_plate_number = vehicle_plate_number
                editable_request.is_auto_booked = False
                editable_request.save()
                messages.success(
                    request,
                    (
                        f"Your parking request was updated to {requested_slot.slot_number} for "
                        f"{selected_booking_date.strftime('%d %b %Y')}. Admin approval is required again."
                    ),
                )
            else:
                parking_request = ParkingRequest(
                    user=request.user,
                    requested_slot=requested_slot,
                    status='Pending',
                    requested_start_time=booking_day_start(selected_booking_date),
                    duration_hours=24,
                    vehicle_plate_number=vehicle_plate_number,
                )
                parking_request.save()
                messages.success(
                    request,
                    (
                        f"Slot request sent for {requested_slot.slot_number} in {requested_slot.full_location}. "
                        "You can track it from the request status page."
                    ),
                )

            if request.user.can_use_auto_booking and form.cleaned_data.get('enable_auto_book'):
                weekdays = ','.join(sorted(form.cleaned_data.get('recurring_weekdays') or []))
                end_date = form.cleaned_data['recurring_end_date']
                auto_rule, created = AutoBookingRule.objects.update_or_create(
                    user=request.user,
                    requested_slot=requested_slot,
                    defaults={
                        'vehicle_plate_number': vehicle_plate_number,
                        'weekdays': weekdays,
                        'start_date': selected_booking_date,
                        'end_date': end_date,
                        'is_active': True,
                    },
                )
                messages.success(
                    request,
                    (
                        'Recurring auto-booking is now active. '
                        'ParkEase will create the next matching request whenever you have no pending request or active booking.'
                    ),
                )
            return redirect('request_status')
    else:
        if editable_request and 'booking_date' not in request.GET and editable_request.requested_start_time:
            selected_booking_date = timezone.localtime(editable_request.requested_start_time).date()
        if requested_slot.id in reserved_slot_ids_for_date(
            selected_booking_date,
            exclude_request_id=getattr(editable_request, 'id', None),
            exclude_assignment_id=getattr(active_assignment, 'id', None) if editable_request else None,
        ):
            messages.error(request, 'This slot is already reserved for the selected date.')
            edit_query = f'&edit_request={editable_request.id}' if editable_request else ''
            return redirect(
                f"{reverse('submit_parking_request')}?area={requested_slot.area}&level={requested_slot.basement_level}&booking_date={selected_booking_date.isoformat()}{edit_query}"
            )
        initial = {
            'requested_start_time': selected_booking_date.strftime('%Y-%m-%d'),
            'vehicle_plate_number': editable_request.vehicle_plate_number if editable_request and editable_request.vehicle_plate_number else (request.user.saved_vehicle_numbers[0] if request.user.saved_vehicle_numbers else ''),
        }
        auto_rule = AutoBookingRule.objects.filter(user=request.user, requested_slot=requested_slot, is_active=True).first()
        if auto_rule:
            initial.update({
                'enable_auto_book': True,
                'recurring_weekdays': [str(day) for day in auto_rule.weekday_numbers],
                'recurring_end_date': auto_rule.end_date.strftime('%Y-%m-%d'),
            })
        form = ParkingRequestForm(initial=initial, user=request.user)

    return render(request, 'parking/request_confirm.html', {
        'editable_request': editable_request,
        'requested_slot': requested_slot,
        'form': form,
        'selected_booking_date': selected_booking_date,
        'saved_vehicle_count': len(request.user.saved_vehicle_numbers),
    })

@user_required
def request_status(request):
    sync_auto_booking_rules(user=request.user)
    requests = ParkingRequest.objects.filter(user=request.user).select_related('requested_slot').order_by('-created_at')
    active_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first()
    auto_booking_rules = AutoBookingRule.objects.filter(user=request.user).select_related('requested_slot').order_by('-updated_at')
    
    # Identify the request that corresponds to the active assignment
    # Since users can only have 1 active assignment, the most recent Approved request is the one.
    latest_approved_req = None
    if active_assignment:
        latest_approved_req = requests.filter(status='Approved').first()
        
    return render(request, 'parking/request_status.html', {
        'requests': requests,
        'active_assignment': active_assignment,
        'auto_booking_rules': auto_booking_rules,
        'latest_approved_req': latest_approved_req,
        'now': timezone.now(),
    })


@user_required
def toggle_auto_booking_rule(request, rule_id):
    rule = get_object_or_404(AutoBookingRule, id=rule_id, user=request.user)
    if request.method == 'POST':
        if not request.user.can_use_auto_booking:
            messages.error(request, 'Auto-booking is available on the Pro and Premium Pass only.')
        else:
            rule.is_active = not rule.is_active
            rule.save(update_fields=['is_active', 'updated_at'])
            messages.success(
                request,
                f'Auto-booking for {rule.requested_slot.slot_number} is now {"active" if rule.is_active else "paused"}.',
            )
    return redirect('request_status')


@user_required
def delete_auto_booking_rule(request, rule_id):
    rule = get_object_or_404(AutoBookingRule, id=rule_id, user=request.user)
    if request.method == 'POST':
        slot_number = rule.requested_slot.slot_number
        rule.delete()
        messages.success(request, f'Auto-booking for {slot_number} was removed.')
    return redirect('request_status')


@user_required
def cancel_parking_request(request, req_id):
    parking_request = get_object_or_404(
        ParkingRequest,
        id=req_id,
        user=request.user,
        status='Pending',
    )
    if request.method == 'POST':
        parking_request.status = 'Cancelled'
        parking_request.save()
        messages.success(request, 'Your pending parking request has been cancelled.')
    return redirect('request_status')

@user_required
def user_release_assignment(request):
    if request.method == 'POST':
        assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first()
        if assignment:
            assignment.status = 'Released'
            assignment.released_at = timezone.now()
            assignment.overstay_amount = Decimal('0.00')
            assignment.save()
            
            # Free slot
            slot = assignment.slot
            slot.status = 'Free'
            slot.save()
            messages.success(
                request,
                f'You have successfully released slot {slot.slot_number}.',
            )
        else:
            messages.error(request, 'No active slot assignment found to release.')
    return redirect('user_dashboard')

@admin_required
def admin_pending_requests(request):
    sync_auto_booking_rules()
    priority_order = Case(
        When(user__parking_pass='Premium', then=Value(0)),
        When(user__parking_pass='Pro', then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    requests = ParkingRequest.objects.filter(status='Pending').select_related('user', 'requested_slot').annotate(
        pass_priority=priority_order
    ).order_by('pass_priority', 'created_at')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        requests = requests.filter(requested_slot__area=scope_area)
    return render(request, 'parking/admin_pending_requests.html', {
        'requests': requests,
    })

@admin_required
def admin_assign_slot(request, req_id):
    request_queryset = ParkingRequest.objects.select_related('user', 'requested_slot')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        request_queryset = request_queryset.filter(requested_slot__area=scope_area)
    parking_request = get_object_or_404(request_queryset, id=req_id)
    if parking_request.status != 'Pending':
        messages.warning(request, 'This request is no longer pending approval.')
        return redirect('admin_pending_requests')
    
    booking_date = timezone.localtime(parking_request.requested_start_time).date() if parking_request.requested_start_time else timezone.localdate()
    reserved_slot_ids = reserved_slot_ids_for_date(booking_date, exclude_request_id=parking_request.id)

    if request.method == 'POST':
        slot = parking_request.requested_slot
        if slot is None:
            slot_id = request.POST.get('slot_id')
            if slot_id:
                slot = get_object_or_404(slot_queryset_for_admin(request), id=slot_id, is_active=True)

        if slot:
            slot.refresh_from_db()

            if not slot.is_active or slot.id in reserved_slot_ids:
                messages.error(request, f'The requested slot is not available for {booking_date.strftime("%d %b %Y")}.')
                return redirect('admin_pending_requests')
            if not slot_is_accessible_for_user(parking_request.user, slot):
                messages.error(request, 'This slot requires the Premium Pass.')
                return redirect('admin_pending_requests')

            # Check if user already has active assignment
            if SlotAssignment.objects.filter(user=parking_request.user, status='Active').exists():
                messages.error(request, 'User already has an active slot assignment.')
                return redirect('admin_pending_requests')

            booked_start_time = parking_request.requested_start_time or timezone.now()
            booked_end_time = parking_request.requested_end_time or (booked_start_time + timezone.timedelta(days=1))

            SlotAssignment.objects.create(
                user=parking_request.user,
                slot=slot,
                status='Active',
                booked_start_time=booked_start_time,
                booked_end_time=booked_end_time,
                booked_amount=compute_booked_amount(parking_request.duration_hours),
                vehicle_plate_number=parking_request.vehicle_plate_number,
            )
            
            # Only mark the slot globally assigned when the booking date is current/past.
            slot.status = 'Assigned' if booked_start_time.date() <= timezone.localdate() else 'Free'
            slot.save()
            
            # Update Request status
            parking_request.status = 'Approved'
            parking_request.save()
            email_result = send_real_user_email(
                parking_request.user,
                'ParkEase booking approved',
                (
                    f'Hi {parking_request.user.get_full_name() or parking_request.user.username},\n\n'
                    f'Your parking booking has been approved.\n'
                    f'Slot: {slot.slot_number} ({slot.full_location})\n'
                    f'Parking date: {booked_start_time.strftime("%d %b %Y")}\n\n'
                    'Thank you for using ParkEase.'
                ),
            )

            messages.success(
                request,
                (
                    f'Slot {slot.slot_number} successfully assigned to {parking_request.user.username}. '
                    f'{notification_channel_text(email_result)}'
                ),
            )
            return redirect('admin_pending_requests')

    free_slots = slot_queryset_for_admin(request).filter(is_active=True).exclude(id__in=reserved_slot_ids).order_by('area', 'basement_level', 'slot_number')
    if not parking_request.user.can_book_vip_slots:
        free_slots = [slot for slot in free_slots if not slot.is_vip]
    return render(request, 'parking/admin_assign_slot.html', {
        'parking_request': parking_request,
        'free_slots': free_slots,
        'booking_date': booking_date,
    })
    
@admin_required
def admin_active_assignments(request):
    assignments = SlotAssignment.objects.filter(status='Active').select_related('user', 'slot').order_by('booked_start_time', '-assigned_at')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    return render(request, 'parking/admin_active_assignments.html', {
        'assignments': assignments,
        'now': timezone.now(),
    })
    
@admin_required
def admin_release_assignment(request, assignment_id):
    assignments = SlotAssignment.objects.filter(status='Active')
    scope_area = get_admin_scope_area(request.user)
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    assignment = get_object_or_404(assignments, id=assignment_id)
    if request.method == 'POST':
        assignment.status = 'Released'
        assignment.released_at = timezone.now()
        assignment.overstay_amount = Decimal('0.00')
        assignment.save()
        
        # Free slot
        slot = assignment.slot
        slot.status = 'Free'
        slot.save()
        messages.success(request, f'Slot {slot.slot_number} has been released.')
    return redirect('admin_active_assignments')


@admin_required
def admin_validate_assignment_qr(request, token):
    try:
        payload = signing.loads(token, salt='parkease-assignment-qr', max_age=60 * 60 * 12)
        assignment = SlotAssignment.objects.select_related('user', 'slot').get(
            id=payload['assignment_id'],
            slot_id=payload['slot_id'],
            user_id=payload['user_id'],
        )
        is_valid = assignment.status == 'Active' and assignment.slot.status == 'Assigned'
    except (signing.BadSignature, signing.SignatureExpired, SlotAssignment.DoesNotExist, KeyError):
        assignment = None
        is_valid = False

    return render(request, 'parking/admin_validate_assignment_qr.html', {
        'assignment': assignment,
        'is_valid': is_valid,
    })
