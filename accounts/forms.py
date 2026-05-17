from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, UserVehicle

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'mobile_number', 'vehicle_number')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class AdminCreationForm(UserCreationForm):
    assigned_area = forms.ChoiceField(choices=User.AREA_CHOICES)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'mobile_number', 'assigned_area')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
        self.fields['mobile_number'].required = False
        self.fields['email'].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'Admin'
        user.is_staff = True
        if commit:
            user.save()
        return user

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            'first_name',
            'last_name',
            'username',
            'email',
            'mobile_number',
            'vehicle_number',
            'profile_picture',
            'assigned_area',
        )
        widgets = {
            'profile_picture': forms.FileInput(),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.role != 'Admin':
            self.fields.pop('assigned_area', None)
        self.fields['vehicle_number'].label = 'Primary Vehicle Number'
        self.fields['vehicle_number'].help_text = 'This is your default vehicle for bookings and gate scans.'
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class UserVehicleForm(forms.ModelForm):
    class Meta:
        model = UserVehicle
        fields = ('nickname', 'plate_number')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nickname'].required = False
        self.fields['nickname'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Example: Office Car',
        })
        self.fields['plate_number'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Example: GJ01AB1234',
        })
