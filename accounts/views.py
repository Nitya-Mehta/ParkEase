import json
import os
from collections import Counter
from decimal import Decimal
from urllib import error, request as urllib_request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import AdminCreationForm, CustomUserCreationForm, UserProfileForm, UserVehicleForm
from .models import UserVehicle

User = get_user_model()

def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = 'User' # Enforce User role for all new signups for safety
            user.save()
            login(request, user)
            messages.success(request, 'Registration successful. Welcome!')
            return redirect('home')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def create_admin_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'Only superusers can create admin accounts.')
        return redirect('home')

    if request.method == 'POST':
        form = AdminCreationForm(request.POST)
        if form.is_valid():
            admin_user = form.save()
            messages.success(request, f'Admin account for {admin_user.username} created successfully.')
            return redirect('create_admin')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = AdminCreationForm()

    return render(request, 'accounts/create_admin.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {username}!')
                return redirect('home')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
    
    # Add form-control class to all inputs
    for field in form.fields.values():
        field.widget.attrs['class'] = 'form-control'
        
    return render(request, 'accounts/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, 'You have successfully logged out.')
    return redirect('login')

def home_view(request):
    if request.user.is_authenticated:
        if request.user.role == 'Admin':
            return redirect('admin_dashboard')
        else:
            return redirect('user_dashboard')
    return render(request, 'home.html')

def features_view(request):
    return render(request, 'features.html')

def about_view(request):
    return render(request, 'about.html')

from .decorators import user_required, admin_required
from parking.models import ParkingSlot, ParkingRequest, SlotAssignment
from parking.location_data import google_maps_url
from parking.views import (
    build_assignment_qr_image,
    build_assignment_qr_token,
    create_razorpay_order,
    razorpay_is_configured,
    sync_auto_booking_rules,
    verify_razorpay_payment_signature,
)
from complaints.models import Complaint


AREA_OPTIONS = [choice[0] for choice in ParkingSlot.AREA_CHOICES]
BASEMENT_OPTIONS = [choice[0] for choice in ParkingSlot.BASEMENT_CHOICES]
CHATBOT_OUT_OF_SCOPE_REPLY = (
    'I can help with ParkEase website questions and normal conversation only.'
)
CHATBOT_NORMAL_CONVERSATION_KEYWORDS = {
    'hi', 'hello', 'hey', 'thanks', 'thank you', 'bye', 'good morning',
    'good afternoon', 'good evening', 'how are you', 'who are you',
    'what can you do', 'help', 'okay', 'ok', 'nice', 'cool',
}
CHATBOT_WEBSITE_KEYWORDS = {
    'parkease', 'website', 'site', 'page', 'pages', 'login', 'register',
    'signup', 'sign up', 'dashboard', 'profile', 'slot', 'parking',
    'request', 'complaint', 'availability', 'assign', 'approval',
    'status', 'map', 'location', 'admin', 'user', 'account',
}
CHATBOT_BLOCKED_KEYWORDS = {
    'medical', 'medicine', 'doctor', 'diagnosis', 'legal', 'lawyer', 'law',
    'finance', 'financial', 'invest', 'stock', 'crypto', 'tax', 'resume',
    'cv', 'homework', 'assignment', 'exam', 'coding', 'code', 'python',
    'java', 'javascript', 'react', 'django', 'sql', 'politics', 'election',
    'chemistry', 'physics', 'biology', 'math', 'mathematics',
}

PASS_PLANS = {
    'Free': {
        'name': 'Free Pass',
        'price': Decimal('0.00'),
        'monthly_label': 'Rs. 0',
        'tagline': 'Start booking with full location access and your saved vehicles.',
        'highlight': 'Best for occasional parkers',
        'accent': 'free',
        'booking_window': 'Book up to 3 days in advance',
        'discount': 'No parking discount',
        'admin_priority': 'Standard approval order',
        'auto_booking': 'Not included',
        'vip_access': 'No VIP bay access',
        'can': [
            'Book across all standard slots in every location',
            'Save and switch between multiple vehicles',
            'Track request history and active assignments',
        ],
        'cannot': [
            'Cannot auto-book recurring dates',
            'Cannot reserve VIP cleaned-and-serviced bays',
            'Cannot jump ahead of Pro or Premium requests',
        ],
    },
    'Pro': {
        'name': 'Pro Pass',
        'price': Decimal('499.00'),
        'monthly_label': 'Rs. 499 / month',
        'tagline': 'For daily commuters who want recurring auto-booking and lower parking costs.',
        'highlight': 'Most popular for regular office parking',
        'accent': 'pro',
        'booking_window': 'Book anytime in advance',
        'discount': '10% lower parking charges on every completed stay',
        'admin_priority': 'Placed above Free requests',
        'auto_booking': 'Auto-book selected dates and weekdays for a full month ahead',
        'vip_access': 'No VIP bay access',
        'can': [
            'Auto-book selected dates and weekdays for up to 1 full month ahead',
            'Pay 10% less than Free users on parking charges',
            'Appear above Free users in the admin approval queue',
        ],
        'cannot': [
            'Cannot book VIP-only bays',
            'Cannot outrank Premium requests',
        ],
    },
    'Premium': {
        'name': 'Premium Pass',
        'price': Decimal('799.00'),
        'monthly_label': 'Rs. 799 / month',
        'tagline': 'Full priority access with VIP bays, cleaning support, and the strongest savings.',
        'highlight': 'Top-tier access for executives and premium daily users',
        'accent': 'premium',
        'booking_window': 'Book anytime in advance',
        'discount': '20% lower parking charges on every completed stay',
        'admin_priority': 'Always shown first in the admin queue',
        'auto_booking': 'Auto-book selected dates and weekdays for a full month ahead',
        'vip_access': 'VIP-only bays like KA-B3-VIP4 with cleaned and attended area access',
        'can': [
            'Unlock VIP serviced slots and Premium-only bays',
            'Auto-book selected dates and weekdays for up to 1 full month ahead',
            'Pay 20% less than Free users on parking charges',
            'Stay pinned to the top of admin pending requests',
        ],
        'cannot': [],
    },
}


def subscription_checkout_session_key(plan_code):
    return f'pass_checkout_{plan_code}'


def subscription_payment_done_session_key(plan_code):
    return f'pass_checkout_done_{plan_code}'


def plan_choices_for_template():
    return [{'code': code, **details} for code, details in PASS_PLANS.items()]


def build_subscription_callback_token(user_id, plan_code, order_id):
    return signing.dumps(
        {
            'user_id': user_id,
            'plan_code': plan_code,
            'order_id': order_id,
        },
        salt='parkease-subscription-upgrade',
    )


def read_subscription_callback_token(token):
    return signing.loads(token, salt='parkease-subscription-upgrade', max_age=60 * 60)


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


def build_basement_summaries(area, base_queryset, area_options=None):
    area_options = area_options or AREA_OPTIONS
    summaries = []
    for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
        area_level_queryset = base_queryset.filter(area=area, basement_level=basement_value, is_active=True)
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
            'total_slots': area_level_queryset.count(),
            'free_slots': area_level_queryset.filter(status='Free').count(),
            'free_counts_text': '|'.join(f'{option}:{count}' for option, count in free_counts.items()),
        })
    return summaries


def build_slot_panels(area_options, base_queryset):
    panels = []
    for area in area_options:
        levels = []
        for basement_value, basement_label in ParkingSlot.BASEMENT_CHOICES:
            levels.append({
                'value': basement_value,
                'label': basement_label,
                'slots': list(base_queryset.filter(area=area, basement_level=basement_value).order_by('slot_number')),
            })
        panels.append({
            'area': area,
            'levels': levels,
        })
    return panels


def annotate_slot_presence(slots, active_assignments):
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


def is_normal_conversation(text):
    stripped = text.strip()
    if not stripped:
        return False

    if stripped in CHATBOT_NORMAL_CONVERSATION_KEYWORDS:
        return True

    if len(stripped.split()) <= 6 and any(
        phrase in stripped for phrase in CHATBOT_NORMAL_CONVERSATION_KEYWORDS
    ):
        return True

    return False


def is_website_question(text):
    return any(keyword in text for keyword in CHATBOT_WEBSITE_KEYWORDS)


def is_out_of_scope_question(text):
    return any(keyword in text for keyword in CHATBOT_BLOCKED_KEYWORDS)


def get_parkease_chatbot_context(user):
    return (
        f'You are the ParkEase website assistant for user "{user.username}" with role "{user.role}". '
        'You may help with ParkEase website usage, pages, parking slots, requests, complaints, '
        'profile updates, dashboard navigation, and normal friendly conversation. '
        'Do not help with coding, medicine, law, finance, schoolwork, politics, or other outside topics. '
        'If a request is outside ParkEase website help or normal conversation, reply exactly with: '
        f'"{CHATBOT_OUT_OF_SCOPE_REPLY}" '
        'Keep replies short, clear, and practical.'
    )


def get_gemini_chatbot_reply(user, question):
    api_key = getattr(settings, 'GEMINI_API_KEY', '').strip() or os.getenv('GEMINI_API_KEY', '').strip()
    if not api_key:
        return None

    model = getattr(settings, 'GEMINI_CHATBOT_MODEL', 'gemini-2.5-flash-lite')
    payload = {
        'system_instruction': {
            'parts': [
                {'text': get_parkease_chatbot_context(user)},
            ],
        },
        'contents': [
            {
                'role': 'user',
                'parts': [
                    {'text': question},
                ],
            },
        ],
    }
    req = urllib_request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'x-goog-api-key': api_key,
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode('utf-8'))
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None

    for candidate in body.get('candidates', []):
        parts = candidate.get('content', {}).get('parts', [])
        text_parts = [part.get('text', '').strip() for part in parts if part.get('text')]
        if text_parts:
            return '\n'.join(text_parts).strip()

    return None


def assignment_queryset_for_scope(scope_area=None):
    assignments = SlotAssignment.objects.select_related('user', 'slot')
    if scope_area:
        assignments = assignments.filter(slot__area=scope_area)
    return assignments


def build_peak_usage_periods(assignments):
    days = Counter(
        timezone.localtime(assignment.effective_start_time).strftime('%d %b')
        for assignment in assignments
    )
    return [
        {'label': label, 'count': count}
        for label, count in days.most_common(3)
    ]


def build_bar_series(items):
    max_value = max((item['value'] for item in items), default=0)
    for item in items:
        item['percent'] = 0 if max_value == 0 else max(8, round((item['value'] / max_value) * 100))
    return items


def build_user_request_status_stats(user):
    statuses = ['Pending', 'Approved', 'Rejected', 'Cancelled']
    counts = {
        status: ParkingRequest.objects.filter(user=user, status=status).count()
        for status in statuses
    }
    return [
        {'label': status, 'value': counts[status]}
        for status in statuses
    ]


def build_user_area_history_stats(user):
    area_counts = Counter(
        assignment.slot.area
        for assignment in SlotAssignment.objects.filter(user=user).select_related('slot')
    )
    return build_bar_series([
        {'label': area, 'value': area_counts.get(area, 0)}
        for area in AREA_OPTIONS
    ])


def build_admin_area_capacity_stats(slot_queryset, active_assignments, panel_areas):
    inside_slot_ids = {assignment.slot_id for assignment in active_assignments if assignment.entered_at}
    assigned_slot_ids = {assignment.slot_id for assignment in active_assignments}
    items = []
    for area in panel_areas:
        area_slots = list(slot_queryset.filter(area=area, is_active=True))
        total = len(area_slots)
        free = sum(1 for slot in area_slots if slot.status == 'Free' and slot.id not in assigned_slot_ids)
        inside = sum(1 for slot in area_slots if slot.id in inside_slot_ids)
        outside = sum(1 for slot in area_slots if slot.id in assigned_slot_ids and slot.id not in inside_slot_ids)
        occupancy_rate = 0 if total == 0 else round(((inside + outside) / total) * 100)
        items.append({
            'label': area,
            'value': total - free,
            'free': free,
            'inside': inside,
            'outside': outside,
            'total': total,
            'occupancy_rate': occupancy_rate,
        })
    return build_bar_series(items)


def build_recent_request_volume(request_queryset, days=7):
    today = timezone.localdate()
    items = []
    for offset in range(days - 1, -1, -1):
        day = today - timezone.timedelta(days=offset)
        value = request_queryset.filter(created_at__date=day).count()
        items.append({
            'label': day.strftime('%d %b'),
            'value': value,
        })
    return build_bar_series(items)


def build_status_breakdown(request_queryset):
    labels = ['Pending', 'Approved', 'Rejected', 'Cancelled']
    items = [
        {'label': label, 'value': request_queryset.filter(status=label).count()}
        for label in labels
    ]
    total = sum(item['value'] for item in items)
    for item in items:
        item['percent_of_total'] = 0 if total == 0 else round((item['value'] / total) * 100)
    return items


@user_required
def user_dashboard(request):
    sync_auto_booking_rules(user=request.user)
    try:
        assignment = SlotAssignment.objects.get(user=request.user, status='Active')
    except SlotAssignment.DoesNotExist:
        assignment = None
    user_requests = ParkingRequest.objects.filter(user=request.user).select_related('requested_slot')
    pending_request = user_requests.filter(status='Pending').first()
    selected_area = get_selected_area(request)
    selected_level = get_selected_level(request)
    all_slots = ParkingSlot.objects.filter(area=selected_area, basement_level=selected_level).order_by('slot_number')
    user_assignments = SlotAssignment.objects.filter(user=request.user).select_related('slot')
    resolved_complaints = Complaint.objects.filter(user=request.user, status='Resolved').count()
    open_complaints = Complaint.objects.filter(user=request.user, status='Open').count()
    user_request_status_stats = build_user_request_status_stats(request.user)
    user_area_history_stats = build_user_area_history_stats(request.user)
    
    context = {
        'assignment': assignment,
        'pending_request': pending_request,
        'now': timezone.now(),
        'saved_vehicle_count': len(request.user.saved_vehicle_numbers),
        'parking_pass_label': request.user.parking_pass_label,
        'assignment_maps_url': google_maps_url(assignment.slot.area) if assignment else None,
        'assignment_qr_image': None,
        'assignment_qr_url': None,
        'all_slots': all_slots,
        'user_total_requests': user_requests.count(),
        'user_total_assignments': user_assignments.count(),
        'user_open_complaints': open_complaints,
        'user_resolved_complaints': resolved_complaints,
        'user_request_status_stats': user_request_status_stats,
        'user_area_history_stats': user_area_history_stats,
        'selected_area': selected_area,
        'selected_level': selected_level,
        'selected_level_label': dict(ParkingSlot.BASEMENT_CHOICES).get(selected_level, selected_level),
        'area_options': AREA_OPTIONS,
        'basement_summaries': build_basement_summaries(selected_area, ParkingSlot.objects.all(), AREA_OPTIONS),
        'slot_panels': build_slot_panels(AREA_OPTIONS, ParkingSlot.objects.all()),
    }
    if assignment:
        qr_token = build_assignment_qr_token(assignment)
        validation_url = request.build_absolute_uri(f'/parking/admin/assignments/validate/{qr_token}/')
        context['assignment_qr_url'] = validation_url
        context['assignment_qr_image'] = build_assignment_qr_image(validation_url)
    return render(request, 'accounts/user_dashboard.html', context)

@admin_required
def admin_dashboard(request):
    sync_auto_booking_rules()
    scope_area = request.user.assigned_area or None
    selected_area = get_selected_area(request, allowed_area=scope_area)
    selected_level = get_selected_level(request)
    slot_queryset = ParkingSlot.objects.all()
    request_queryset = ParkingRequest.objects.all()
    complaint_queryset = Complaint.objects.all()
    assignment_queryset = assignment_queryset_for_scope(scope_area)
    if scope_area:
        slot_queryset = slot_queryset.filter(area=scope_area)
        request_queryset = request_queryset.filter(requested_slot__area=scope_area)
        complaint_queryset = complaint_queryset.filter(slot__area=scope_area)

    panel_areas = [scope_area] if scope_area else AREA_OPTIONS
    active_assignments = list(assignment_queryset.filter(status='Active').order_by('booked_end_time', '-assigned_at'))
    active_parked = [assignment for assignment in active_assignments if assignment.is_currently_parked]
    peak_usage_periods = build_peak_usage_periods(assignment_queryset.filter(assigned_at__date__gte=timezone.localdate() - timezone.timedelta(days=30)))
    request_status_breakdown = build_status_breakdown(request_queryset)
    area_capacity_stats = build_admin_area_capacity_stats(slot_queryset, active_assignments, panel_areas)
    recent_request_volume = build_recent_request_volume(request_queryset)
    dashboard_slots = list(slot_queryset.filter(area=selected_area, basement_level=selected_level).order_by('slot_number'))
    annotate_slot_presence(dashboard_slots, active_assignments)
    slot_panels = build_slot_panels(panel_areas, slot_queryset)
    for area_panel in slot_panels:
        for level_panel in area_panel['levels']:
            annotate_slot_presence(level_panel['slots'], active_assignments)
    assigned_slots = slot_queryset.filter(status='Assigned').count()

    context = {
        'total_slots': slot_queryset.count(),
        'free_slots': slot_queryset.filter(status='Free').count(),
        'assigned_slots': assigned_slots,
        'active_vehicles': len(active_parked),
        'pending_requests': request_queryset.filter(status='Pending').count(),
        'open_complaints': complaint_queryset.filter(status='Open').count(),
        'peak_usage_periods': peak_usage_periods,
        'request_status_breakdown': request_status_breakdown,
        'area_capacity_stats': area_capacity_stats,
        'recent_request_volume': recent_request_volume,
        'now': timezone.now(),
        'all_slots': dashboard_slots,
        'selected_area': selected_area,
        'selected_level': selected_level,
        'selected_level_label': dict(ParkingSlot.BASEMENT_CHOICES).get(selected_level, selected_level),
        'area_options': panel_areas,
        'admin_scope_area': scope_area,
        'basement_summaries': build_basement_summaries(selected_area, slot_queryset, panel_areas),
        'slot_panels': slot_panels,
    }
    return render(request, 'accounts/admin_dashboard.html', context)

@login_required
def profile_view(request):
    vehicle_form = UserVehicleForm()
    if request.method == 'POST':
        action = request.POST.get('action', 'profile')
        if action == 'add_vehicle':
            form = UserProfileForm(instance=request.user)
            vehicle_form = UserVehicleForm(request.POST)
            if vehicle_form.is_valid():
                vehicle = vehicle_form.save(commit=False)
                vehicle.user = request.user
                vehicle.save()
                messages.success(request, 'Additional vehicle saved successfully.')
                return redirect('profile')
            messages.error(request, 'Please correct the vehicle details below.')
        elif action == 'delete_vehicle':
            form = UserProfileForm(instance=request.user)
            vehicle_id = request.POST.get('vehicle_id')
            vehicle = get_object_or_404(UserVehicle, id=vehicle_id, user=request.user)
            vehicle.delete()
            messages.success(request, 'Saved vehicle removed.')
            return redirect('profile')
        else:
            form = UserProfileForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Your profile has been updated successfully!')
                return redirect('profile')
            messages.error(request, 'Please correct the error below.')
    else:
        form = UserProfileForm(instance=request.user)
    
    return render(request, 'accounts/profile.html', {
        'form': form,
        'vehicle_form': vehicle_form,
        'saved_vehicles': request.user.saved_vehicles.all(),
    })


@login_required
def subscriptions_view(request):
    if request.user.role == 'Admin':
        messages.info(request, 'Subscription passes are available for parking users only.')
        return redirect('admin_dashboard')

    return render(request, 'accounts/subscriptions.html', {
        'plans': plan_choices_for_template(),
        'current_pass': request.user.parking_pass,
    })


@login_required
def subscription_checkout_view(request, plan_code):
    if request.user.role == 'Admin':
        messages.info(request, 'Subscription passes are available for parking users only.')
        return redirect('admin_dashboard')

    plan = PASS_PLANS.get(plan_code)
    if not plan:
        messages.error(request, 'That subscription plan does not exist.')
        return redirect('subscriptions')

    if plan_code == 'Free':
        request.user.parking_pass = 'Free'
        request.user.save(update_fields=['parking_pass'])
        messages.success(request, 'Your account is now on the Free Pass.')
        return redirect('subscriptions')

    payment_done = request.session.get(subscription_payment_done_session_key(plan_code), False)
    checkout_state = request.session.get(subscription_checkout_session_key(plan_code), {})
    gateway_ready = razorpay_is_configured()
    amount_paise = int(plan['price'] * 100)

    if not payment_done and gateway_ready and not checkout_state.get('order_id'):
        try:
            order = create_razorpay_order(
                amount_paise=amount_paise,
                receipt=f'parkease-pass-{request.user.id}-{plan_code.lower()}-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                notes={
                    'user_id': str(request.user.id),
                    'username': request.user.username,
                    'plan_code': plan_code,
                },
            )
            checkout_state = {
                'order_id': order.get('id', ''),
                'amount_paise': order.get('amount', amount_paise),
                'currency': order.get('currency', 'INR'),
            }
            checkout_state['callback_token'] = build_subscription_callback_token(
                request.user.id,
                plan_code,
                checkout_state['order_id'],
            )
            request.session[subscription_checkout_session_key(plan_code)] = checkout_state
        except ValueError as exc:
            gateway_ready = False
            messages.error(request, str(exc))

    if not gateway_ready and not payment_done:
        messages.warning(
            request,
            'Razorpay is not ready yet. Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in the project .env file.',
        )

    return render(request, 'accounts/subscription_checkout.html', {
        'plan_code': plan_code,
        'plan': plan,
        'payment_done': payment_done,
        'checkout_state': checkout_state,
        'gateway_ready': gateway_ready and bool(checkout_state.get('order_id')),
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'razorpay_company_name': settings.RAZORPAY_COMPANY_NAME,
        'razorpay_callback_url': request.build_absolute_uri(
            f"{reverse('subscription_verify', args=[plan_code])}?token={checkout_state.get('callback_token', '')}"
        ),
    })


@csrf_exempt
def subscription_verify_view(request, plan_code):
    plan = PASS_PLANS.get(plan_code)
    if not plan or plan_code == 'Free':
        if request.user.is_authenticated:
            messages.error(request, 'That subscription plan cannot be verified.')
            return redirect('subscriptions')
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'That subscription plan could not be verified.',
        })

    if not razorpay_is_configured():
        if request.user.is_authenticated:
            messages.error(request, 'Razorpay keys are missing. Configure them before verifying payments.')
            return redirect('subscription_checkout', plan_code=plan_code)
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'Razorpay keys are missing on the server.',
        })

    callback_token = request.GET.get('token', '').strip()
    try:
        callback_payload = read_subscription_callback_token(callback_token)
    except signing.BadSignature:
        if request.user.is_authenticated:
            messages.error(request, 'The subscription callback token is invalid or expired.')
            return redirect('subscriptions')
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'The subscription callback token is invalid or expired.',
        })

    if callback_payload.get('plan_code') != plan_code:
        if request.user.is_authenticated:
            messages.error(request, 'The subscription callback token does not match this plan.')
            return redirect('subscriptions')
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'The subscription callback token does not match this plan.',
        })

    subscription_user = get_object_or_404(User, id=callback_payload.get('user_id'), role='User')

    if request.method != 'POST':
        checkout_status = request.GET.get('status', '').strip().lower()
        if checkout_status == 'cancelled':
            return render(request, 'accounts/subscription_callback_result.html', {
                'success': False,
                'title': 'Payment Cancelled',
                'message': f'The {plan["name"]} checkout was cancelled before payment was completed.',
                'return_url': reverse('subscription_checkout', args=[plan_code]),
                'return_label': 'Try Razorpay Again',
            })
        if checkout_status == 'failed':
            failure_reason = request.GET.get('reason', '').strip() or 'Razorpay reported that the payment failed.'
            return render(request, 'accounts/subscription_callback_result.html', {
                'success': False,
                'title': 'Payment Failed',
                'message': failure_reason,
                'return_url': reverse('subscription_checkout', args=[plan_code]),
                'return_label': 'Try Razorpay Again',
            })
        if request.user.is_authenticated and request.user.id == subscription_user.id:
            return redirect('subscription_checkout', plan_code=plan_code)
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Payment Incomplete',
            'message': 'No completed Razorpay payment was received for this checkout.',
            'return_url': reverse('login'),
            'return_label': 'Open ParkEase',
        })

    payment_id = request.POST.get('razorpay_payment_id', '').strip()
    order_id = request.POST.get('razorpay_order_id', '').strip()
    signature = request.POST.get('razorpay_signature', '').strip()
    error_code = request.POST.get('error[code]', '').strip()
    error_description = request.POST.get('error[description]', '').strip()

    if error_code or error_description:
        message = f'Razorpay reported a failed payment: {error_description or error_code}.'
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Payment Failed',
            'message': message,
            'return_url': reverse('subscription_checkout', args=[plan_code]),
            'return_label': 'Try Razorpay Again',
        })

    if not payment_id or not order_id or not signature:
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Payment Incomplete',
            'message': 'Payment was not completed in Razorpay.',
            'return_url': reverse('subscription_checkout', args=[plan_code]),
            'return_label': 'Try Razorpay Again',
        })

    expected_order_id = callback_payload.get('order_id')
    if expected_order_id and expected_order_id != order_id:
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'The returned Razorpay order did not match this subscription checkout.',
            'return_url': reverse('subscription_checkout', args=[plan_code]),
            'return_label': 'Try Razorpay Again',
        })

    if not verify_razorpay_payment_signature(order_id, payment_id, signature):
        return render(request, 'accounts/subscription_callback_result.html', {
            'success': False,
            'title': 'Plan Verification Failed',
            'message': 'Razorpay payment verification failed.',
            'return_url': reverse('subscription_checkout', args=[plan_code]),
            'return_label': 'Try Razorpay Again',
        })

    subscription_user.parking_pass = plan_code
    subscription_user.save(update_fields=['parking_pass'])

    if request.user.is_authenticated and request.user.id == subscription_user.id:
        checkout_state = request.session.get(subscription_checkout_session_key(plan_code), {})
        request.session[subscription_payment_done_session_key(plan_code)] = True
        request.session[subscription_checkout_session_key(plan_code)] = {
            **checkout_state,
            'payment_id': payment_id,
            'signature': signature,
        }

    return render(request, 'accounts/subscription_callback_result.html', {
        'success': True,
        'title': 'Upgrade Complete',
        'message': f'Your account has been upgraded to the {plan["name"]}. You can return to ParkEase now.',
        'return_url': reverse('subscriptions'),
        'return_label': 'Back To Passes',
    })


@login_required
def chatbot_view(request):
    suggestions = [
        'Where is my slot?',
        'What is my request status?',
        'How do I raise a complaint?',
        'Show parking availability',
        'How do I update my profile?',
    ]
    if request.user.role == 'Admin':
        suggestions = [
            'How many pending requests?',
            'How many open complaints?',
            'Show parking availability',
            'How do I assign a slot?',
        ]
    return render(request, 'accounts/chatbot.html', {'suggestions': suggestions})


@login_required
@require_POST
def chatbot_ask(request):
    question = request.POST.get('message', '').strip()
    if not question:
        return JsonResponse({'reply': 'Please type a question first.'})
    return JsonResponse({'reply': build_chatbot_reply(request.user, question)})


def build_chatbot_reply(user, question):
    text = question.lower()
    if is_out_of_scope_question(text):
        return CHATBOT_OUT_OF_SCOPE_REPLY

    if not (is_website_question(text) or is_normal_conversation(text)):
        return CHATBOT_OUT_OF_SCOPE_REPLY

    assignment = SlotAssignment.objects.filter(user=user, status='Active').select_related('slot').first()
    pending_request = ParkingRequest.objects.filter(user=user, status='Pending').select_related('requested_slot').first()

    if is_normal_conversation(text) and not is_website_question(text):
        gemini_reply = get_gemini_chatbot_reply(user, question)
        if gemini_reply:
            return gemini_reply

        if any(word in text for word in ['thank', 'thanks']):
            return 'You are welcome.'
        if any(word in text for word in ['bye', 'goodbye', 'see you']):
            return 'Bye. I am here whenever you need help with ParkEase.'
        if any(word in text for word in ['how are you']):
            return 'I am doing well and ready to help with ParkEase.'
        return 'Hi. I can help with ParkEase website questions and normal conversation.'

    if any(word in text for word in ['my slot', 'where is my slot', 'assigned', 'location', 'map']):
        if assignment:
            maps_url = google_maps_url(assignment.slot.area)
            return (
                f'Your assigned slot is {assignment.slot.slot_number} at {assignment.slot.full_location}. '
                f'Open Google Maps: {maps_url}'
            )
        if pending_request and pending_request.requested_slot:
            return (
                f'Your request for {pending_request.requested_slot.slot_number} at '
                f'{pending_request.requested_slot.full_location} is still pending.'
            )
        return 'You do not have an assigned slot yet. Go to Choose Parking Spot to request one.'

    if any(word in text for word in ['request', 'pending', 'status', 'approval', 'approved']):
        if pending_request and pending_request.requested_slot:
            return (
                f'Your request for {pending_request.requested_slot.slot_number} is pending admin approval. '
                'You can cancel it from My Requests.'
            )
        latest_request = ParkingRequest.objects.filter(user=user).select_related('requested_slot').order_by('-created_at').first()
        if latest_request:
            slot_text = latest_request.requested_slot.slot_number if latest_request.requested_slot else 'a slot'
            return f'Your latest request for {slot_text} is {latest_request.status}.'
        return 'You have not submitted any parking request yet.'

    if any(word in text for word in ['complaint', 'complain', 'issue', 'occupied', 'blocked']):
        if user.role == 'Admin':
            open_count = Complaint.objects.filter(status='Open').count()
            return f'There are {open_count} open complaints. Open the Complaints page to resolve them.'
        if assignment:
            return 'You can raise a complaint from Complaints > New Complaint. Choose the issue type, upload the image, and submit it.'
        return 'You can raise a complaint only after you have an active assigned parking slot.'

    if any(word in text for word in ['available', 'availability', 'free', 'slots', 'parking']):
        lines = []
        for area in AREA_OPTIONS:
            free_count = ParkingSlot.objects.filter(area=area, status='Free', is_active=True).count()
            lines.append(f'{area}: {free_count} free')
        return 'Current availability: ' + '; '.join(lines) + '.'

    if user.role == 'Admin' and any(word in text for word in ['assign', 'approve']):
        pending_count = ParkingRequest.objects.filter(status='Pending').count()
        return f'There are {pending_count} pending requests. Go to Requests, open a request, and approve the available slot.'

    if user.role == 'Admin' and any(word in text for word in ['dashboard', 'summary', 'report']):
        return (
            f'Admin summary: {ParkingRequest.objects.filter(status="Pending").count()} pending requests, '
            f'{Complaint.objects.filter(status="Open").count()} open complaints, '
            f'{ParkingSlot.objects.filter(status="Free", is_active=True).count()} free slots.'
        )

    if any(word in text for word in ['profile', 'email', 'phone', 'mobile']):
        return 'Go to My Profile to update your email, mobile number, vehicle number, and profile picture.'

    gemini_reply = get_gemini_chatbot_reply(user, question)
    if gemini_reply:
        return gemini_reply

    return (
        'I can help with ParkEase website questions like slot location, request status, complaints, '
        'availability, profile updates, and admin summaries.'
    )
