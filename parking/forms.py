from django import forms
from django.utils import timezone

from .models import AutoBookingRule, ParkingSlot


def recurring_max_end_date(start_date):
    return start_date + timezone.timedelta(days=31)


class ParkingSlotForm(forms.ModelForm):
    class Meta:
        model = ParkingSlot
        fields = ['slot_number', 'area', 'basement_level', 'location', 'status', 'vip_only', 'is_active']
        
    def __init__(self, *args, **kwargs):
        locked_area = kwargs.pop('locked_area', None)
        super().__init__(*args, **kwargs)
        if locked_area:
            self.fields['area'].initial = locked_area
            self.fields['area'].disabled = True
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-control'


class ParkingRequestForm(forms.Form):
    requested_start_time = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )
    vehicle_plate_number = forms.ChoiceField()
    enable_auto_book = forms.BooleanField(required=False)
    recurring_weekdays = forms.MultipleChoiceField(
        required=False,
        choices=AutoBookingRule.WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    recurring_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['requested_start_time'].widget.attrs['class'] = 'form-control'
        self.fields['requested_start_time'].help_text = 'Choose the date you want to park.'
        self.fields['vehicle_plate_number'].widget.attrs['class'] = 'form-control'
        self.fields['vehicle_plate_number'].help_text = 'Choose which of your saved vehicles will use this booking.'
        self.fields['enable_auto_book'].help_text = 'Available on Pro and Premium. ParkEase will create the next matching request automatically.'
        self.fields['recurring_end_date'].widget.attrs['class'] = 'form-control'
        self.fields['recurring_end_date'].help_text = 'Set how long this recurring auto-book rule should continue, up to 1 month ahead.'
        today = timezone.localdate()
        if not self.is_bound:
            self.initial.setdefault('requested_start_time', today.strftime('%Y-%m-%d'))
            self.initial.setdefault('recurring_end_date', (today + timezone.timedelta(days=30)).strftime('%Y-%m-%d'))

        vehicle_choices = []
        if self.user:
            for plate in self.user.saved_vehicle_numbers:
                label = plate
                if plate == self.user.saved_vehicle_numbers[0]:
                    label = f'{plate} (Primary)'
                vehicle_choices.append((plate, label))
        if not vehicle_choices:
            vehicle_choices = [('', 'Add a vehicle in your profile first')]
        self.fields['vehicle_plate_number'].choices = vehicle_choices
        if not self.user or not self.user.can_use_auto_booking:
            self.fields['enable_auto_book'].widget = forms.HiddenInput()
            self.fields['recurring_weekdays'].widget = forms.MultipleHiddenInput()
            self.fields['recurring_end_date'].widget = forms.HiddenInput()

    def clean_requested_start_time(self):
        value = self.cleaned_data['requested_start_time']
        if value < timezone.localdate():
            raise forms.ValidationError('Please choose today or a future date.')
        if self.user and not self.user.can_book_date(value):
            max_date = timezone.localdate() + timezone.timedelta(days=self.user.booking_window_days)
            raise forms.ValidationError(
                f'Your {self.user.parking_pass_label} allows booking until {max_date.strftime("%d %b %Y")}.'
            )
        return value

    def clean(self):
        cleaned_data = super().clean()
        vehicle_plate_number = cleaned_data.get('vehicle_plate_number')
        if self.user and not vehicle_plate_number:
            self.add_error('vehicle_plate_number', 'Please choose a vehicle for this booking.')

        if cleaned_data.get('enable_auto_book'):
            weekdays = cleaned_data.get('recurring_weekdays') or []
            end_date = cleaned_data.get('recurring_end_date')
            start_date = cleaned_data.get('requested_start_time')
            if not self.user or not self.user.can_use_auto_booking:
                self.add_error('enable_auto_book', 'Auto-booking is available on Pro and Premium only.')
            if not weekdays:
                self.add_error('recurring_weekdays', 'Choose at least one day for the recurring rule.')
            if not end_date:
                self.add_error('recurring_end_date', 'Choose when the recurring rule should stop.')
            elif start_date and end_date < start_date:
                self.add_error('recurring_end_date', 'The recurring end date must be on or after the first booking date.')
            elif start_date and end_date > recurring_max_end_date(start_date):
                self.add_error('recurring_end_date', 'Recurring auto-booking can be set for 1 month ahead only.')
        return cleaned_data


class AdminVehicleScanForm(forms.Form):
    gate_mode = forms.ChoiceField(
        choices=[
            ('entry', 'Entry Scan'),
            ('exit', 'Exit Scan'),
        ],
        initial='entry',
        required=False,
    )
    image = forms.ImageField(required=False)
    plate_number = forms.CharField(
        max_length=20,
        required=False,
        help_text='Optional manual override if OCR cannot read the number plate correctly.',
    )
    captured_image_data = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['gate_mode'].widget.attrs.update({
            'class': 'form-control',
        })
        self.fields['image'].widget.attrs.update({
            'class': 'form-control',
            'accept': 'image/*',
            'capture': 'environment',
        })
        self.fields['plate_number'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Example: GJ01AB1234',
        })

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('image') and not cleaned_data.get('captured_image_data'):
            raise forms.ValidationError('Upload an image or capture one from the camera.')
        return cleaned_data
