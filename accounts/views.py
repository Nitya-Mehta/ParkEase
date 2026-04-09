from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from .forms import CustomUserCreationForm, UserProfileForm

from django.contrib.auth import get_user_model
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
    try: 
        if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@gmail.com', 'admin123')
    except:
        pass
    
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
from complaints.models import Complaint

@user_required
def user_dashboard(request):
    try:
        assignment = SlotAssignment.objects.get(user=request.user, status='Active')
    except SlotAssignment.DoesNotExist:
        assignment = None
        
    pending_request = ParkingRequest.objects.filter(user=request.user, status='Pending').first()
    all_slots = ParkingSlot.objects.all().order_by('slot_number')
    
    context = {
        'assignment': assignment,
        'pending_request': pending_request,
        'all_slots': all_slots,
    }
    return render(request, 'accounts/user_dashboard.html', context)

@admin_required
def admin_dashboard(request):
    context = {
        'total_slots': ParkingSlot.objects.count(),
        'free_slots': ParkingSlot.objects.filter(status='Free').count(),
        'assigned_slots': ParkingSlot.objects.filter(status='Assigned').count(),
        'pending_requests': ParkingRequest.objects.filter(status='Pending').count(),
        'open_complaints': Complaint.objects.filter(status='Open').count(),
        'all_slots': ParkingSlot.objects.all().order_by('slot_number'),
    }
    return render(request, 'accounts/admin_dashboard.html', context)

@login_required
def profile_view(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = UserProfileForm(instance=request.user)
    
    return render(request, 'accounts/profile.html', {'form': form})
