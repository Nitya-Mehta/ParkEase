from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import admin_required
from .models import ParkingSlot
from .forms import ParkingSlotForm

@admin_required
def admin_slot_list(request):
    slots = ParkingSlot.objects.all().order_by('slot_number')
    return render(request, 'parking/admin_slot_list.html', {'slots': slots})

@admin_required
def admin_slot_create(request):
    if request.method == 'POST':
        form = ParkingSlotForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Parking slot created successfully.')
            return redirect('admin_slot_list')
    else:
        form = ParkingSlotForm()
    return render(request, 'parking/admin_slot_form.html', {'form': form, 'title': 'Create Parking Slot'})

@admin_required
def admin_slot_edit(request, slot_id):
    slot = get_object_or_404(ParkingSlot, id=slot_id)
    if request.method == 'POST':
        form = ParkingSlotForm(request.POST, instance=slot)
        if form.is_valid():
            form.save()
            messages.success(request, 'Parking slot updated successfully.')
            return redirect('admin_slot_list')
    else:
        form = ParkingSlotForm(instance=slot)
    return render(request, 'parking/admin_slot_form.html', {'form': form, 'title': f'Edit Slot {slot.slot_number}'})

@admin_required
def admin_slot_toggle_active(request, slot_id):
    slot = get_object_or_404(ParkingSlot, id=slot_id)
    slot.is_active = not slot.is_active
    slot.save()
    status_text = "enabled" if slot.is_active else "disabled"
    messages.success(request, f'Slot {slot.slot_number} has been {status_text}.')
    return redirect('admin_slot_list')

@admin_required
def admin_slot_force_release(request, slot_id):
    slot = get_object_or_404(ParkingSlot, id=slot_id)
    if request.method == 'POST' and slot.status == 'Assigned':
        from .models import SlotAssignment
        # Find the active assignment and release it
        assignment = SlotAssignment.objects.filter(slot=slot, status='Active').first()
        if assignment:
            assignment.status = 'Released'
            assignment.save()
        
        # Free the slot
        slot.status = 'Free'
        slot.save()
        messages.success(request, f'Slot {slot.slot_number} has been forcefully freed.')
    return redirect('admin_slot_list')

from accounts.decorators import user_required
from .models import ParkingRequest
from django.db.models import Q

@user_required
def submit_parking_request(request):
    # Check if user already has a pending request
    has_pending = ParkingRequest.objects.filter(user=request.user, status='Pending').exists()
    # Check if user already has an active assignment
    has_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').exists()
    
    if has_pending or has_assignment:
        messages.warning(request, "You already have an active parking request or assignment.")
        return redirect('request_status')
    
    if request.method == 'POST':
        ParkingRequest.objects.create(user=request.user, status='Pending')
        messages.success(request, "Parking request submitted successfully.")
        return redirect('request_status')
        
    return render(request, 'parking/request_submit.html')

@user_required
def request_status(request):
    requests = ParkingRequest.objects.filter(user=request.user).order_by('-created_at')
    active_assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first()
    
    # Identify the request that corresponds to the active assignment
    # Since users can only have 1 active assignment, the most recent Approved request is the one.
    latest_approved_req = None
    if active_assignment:
        latest_approved_req = requests.filter(status='Approved').first()
        
    return render(request, 'parking/request_status.html', {
        'requests': requests,
        'active_assignment': active_assignment,
        'latest_approved_req': latest_approved_req
    })

@user_required
def user_release_assignment(request):
    if request.method == 'POST':
        assignment = SlotAssignment.objects.filter(user=request.user, status='Active').first()
        if assignment:
            # Release assignment
            assignment.status = 'Released'
            assignment.save()
            
            # Free slot
            slot = assignment.slot
            slot.status = 'Free'
            slot.save()
            messages.success(request, f'You have successfully released slot {slot.slot_number}.')
        else:
            messages.error(request, 'No active slot assignment found to release.')
    return redirect('user_dashboard')

from .models import SlotAssignment

@admin_required
def admin_pending_requests(request):
    requests = ParkingRequest.objects.filter(status='Pending').order_by('created_at')
    return render(request, 'parking/admin_pending_requests.html', {'requests': requests})

@admin_required
def admin_assign_slot(request, req_id):
    parking_request = get_object_or_404(ParkingRequest, id=req_id, status='Pending')
    
    if request.method == 'POST':
        slot_id = request.POST.get('slot_id')
        if slot_id:
            slot = get_object_or_404(ParkingSlot, id=slot_id, status='Free', is_active=True)
            
            # Check if user already has active assignment
            if SlotAssignment.objects.filter(user=parking_request.user, status='Active').exists():
                messages.error(request, 'User already has an active slot assignment.')
                return redirect('admin_pending_requests')
                
            # Create assignment
            SlotAssignment.objects.create(user=parking_request.user, slot=slot, status='Active')
            
            # Update Slot status
            slot.status = 'Assigned'
            slot.save()
            
            # Update Request status
            parking_request.status = 'Approved'
            parking_request.save()
            
            messages.success(request, f'Slot {slot.slot_number} successfully assigned to {parking_request.user.username}.')
            return redirect('admin_pending_requests')
            
    # GET request - show available slots
    free_slots = ParkingSlot.objects.filter(status='Free', is_active=True)
    return render(request, 'parking/admin_assign_slot.html', {'parking_request': parking_request, 'free_slots': free_slots})
    
@admin_required
def admin_active_assignments(request):
    assignments = SlotAssignment.objects.filter(status='Active').order_by('-assigned_at')
    return render(request, 'parking/admin_active_assignments.html', {'assignments': assignments})
    
@admin_required
def admin_release_assignment(request, assignment_id):
    assignment = get_object_or_404(SlotAssignment, id=assignment_id, status='Active')
    if request.method == 'POST':
        # Release assignment
        assignment.status = 'Released'
        assignment.save()
        
        # Free slot
        slot = assignment.slot
        slot.status = 'Free'
        slot.save()
        
        messages.success(request, f'Slot {slot.slot_number} has been released.')
    return redirect('admin_active_assignments')
