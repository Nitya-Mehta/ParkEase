from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import user_required, admin_required
from accounts.models import User
from notifications import draft_email_list, notification_channel_text, send_real_user_email
from .models import Complaint
from parking.models import SlotAssignment
from .forms import ComplaintForm


def admin_alert_recipients(slot):
    configured_emails = getattr(settings, 'PARKEASE_ADMIN_EMAILS', [])
    if configured_emails:
        return configured_emails

    admins = User.objects.filter(role='Admin').exclude(email='')
    area_admins = admins.filter(assigned_area=slot.area)
    if area_admins.exists():
        admins = area_admins
    return list(admins.values_list('email', flat=True))

@user_required
def raise_complaint(request):
    # Check if user has an active assignment
    try:
        assignment = SlotAssignment.objects.get(user=request.user, status='Active')
    except SlotAssignment.DoesNotExist:
        messages.error(request, 'You can only raise a complaint if you have an active parking slot.')
        if request.user.role == 'Admin':
            return redirect('admin_dashboard')
        return redirect('user_dashboard')
        
    if request.method == 'POST':
        form = ComplaintForm(request.POST, request.FILES)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.user = request.user
            complaint.slot = assignment.slot
            complaint.save()
            admin_alert_result = draft_email_list(
                admin_alert_recipients(complaint.slot),
                f'New ParkEase complaint for {complaint.slot.area} admin',
                (
                    f'A new complaint has been filed.\n\n'
                    f'User: {complaint.user.username}\n'
                    f'Mobile: {complaint.user.mobile_number or "Not provided"}\n'
                    f'Slot: {complaint.slot.slot_number} ({complaint.slot.full_location})\n'
                    f'Complaint: {complaint.complaint_type}\n'
                    f'Details: {complaint.complaint_details or "Not provided"}\n\n'
                    'Please resolve it within 5 minutes.'
                ),
            )
            messages.success(
                request,
                'Complaint filed successfully. It will be solved within 5 minutes, and you will be notified when it is resolved.',
            )
            if not admin_alert_result.get('email_sent') and not admin_alert_result.get('email_drafted'):
                messages.warning(request, 'Admin email alert could not be created because no admin email is configured.')
            return redirect('user_complaint_status')
    else:
        form = ComplaintForm()
        
    return render(request, 'complaints/raise_complaint.html', {'form': form, 'assignment': assignment})

@user_required
def user_complaint_status(request):
    complaints = Complaint.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'complaints/user_complaint_status.html', {'complaints': complaints})
    
@admin_required
def admin_complaint_list(request):
    complaints = Complaint.objects.select_related('user', 'slot').all().order_by('-created_at')
    if request.user.assigned_area:
        complaints = complaints.filter(slot__area=request.user.assigned_area)
    return render(request, 'complaints/admin_complaint_list.html', {'complaints': complaints})

@admin_required
def admin_resolve_complaint(request, complaint_id):
    complaints = Complaint.objects.all()
    if request.user.assigned_area:
        complaints = complaints.filter(slot__area=request.user.assigned_area)
    complaint = get_object_or_404(complaints, id=complaint_id)
    if request.method == 'POST':
        complaint.status = 'Resolved'
        complaint.save()
        result = send_real_user_email(
            complaint.user,
            'ParkEase complaint resolved',
            (
                f'Hi {complaint.user.get_full_name() or complaint.user.username},\n\n'
                f'Your complaint for slot {complaint.slot.slot_number} has been resolved.\n\n'
                'Thank you for using ParkEase.'
            ),
        )
        messages.success(
            request,
            f'Complaint resolved. {notification_channel_text(result)}',
        )
    return redirect('admin_complaint_list')
