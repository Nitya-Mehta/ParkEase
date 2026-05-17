from django import forms
from .models import Complaint

class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['complaint_type', 'complaint_details', 'vehicle_image']
        widgets = {
            'complaint_details': forms.Textarea(attrs={'rows': 4}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['complaint_type'].label = 'Complaint'
        self.fields['complaint_details'].label = 'Write your complaint'
        self.fields['complaint_details'].required = False
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean(self):
        cleaned_data = super().clean()
        complaint_type = cleaned_data.get('complaint_type')
        complaint_details = cleaned_data.get('complaint_details', '').strip()

        if complaint_type == Complaint.COMPLAINT_TYPE_OTHER and not complaint_details:
            self.add_error('complaint_details', 'Please write your complaint.')

        return cleaned_data
