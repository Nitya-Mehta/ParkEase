from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import user_required, admin_required
from .models import Complaint
from parking.models import SlotAssignment
from .forms import ComplaintForm

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
            messages.success(request, 'Complaint submitted successfully.')
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
    complaints = Complaint.objects.all().order_by('-created_at')
    return render(request, 'complaints/admin_complaint_list.html', {'complaints': complaints})

@admin_required
def admin_resolve_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)
    if request.method == 'POST':
        complaint.status = 'Resolved'
        complaint.save()
        messages.success(request, f'Complaint #{complaint.id} has been resolved.')
    return redirect('admin_complaint_list')
