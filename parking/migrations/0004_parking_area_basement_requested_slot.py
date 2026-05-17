from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


AREA_CHOICES = [
    ('Thaltej', 'TH'),
    ('Navrangpura', 'NA'),
    ('Paldi', 'PA'),
    ('Kalupur', 'KA'),
]

BASEMENT_CHOICES = [
    ('B1', 'Basement -1'),
    ('B2', 'Basement -2'),
    ('B3', 'Basement -3'),
]


def seed_parking_slots(apps, schema_editor):
    ParkingSlot = apps.get_model('parking', 'ParkingSlot')

    for area_name, area_code in AREA_CHOICES:
        for basement_code, basement_label in BASEMENT_CHOICES:
            for spot_number in range(1, 9):
                slot_number = f'{area_code}-{basement_code}-{spot_number:02d}'
                ParkingSlot.objects.get_or_create(
                    slot_number=slot_number,
                    defaults={
                        'area': area_name,
                        'basement_level': basement_code,
                        'location': f'{area_name} {basement_label} Bay {spot_number}',
                        'status': 'Free',
                        'is_active': True,
                    },
                )


class Migration(migrations.Migration):

    dependencies = [
        ('parking', '0003_slotassignment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='parkingslot',
            name='area',
            field=models.CharField(choices=[('Thaltej', 'Thaltej'), ('Navrangpura', 'Navrangpura'), ('Paldi', 'Paldi'), ('Kalupur', 'Kalupur')], default='Thaltej', max_length=20),
        ),
        migrations.AddField(
            model_name='parkingslot',
            name='basement_level',
            field=models.CharField(choices=[('B1', 'Basement -1'), ('B2', 'Basement -2'), ('B3', 'Basement -3')], default='B1', max_length=2),
        ),
        migrations.AddField(
            model_name='parkingrequest',
            name='requested_slot',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requested_by', to='parking.parkingslot'),
        ),
        migrations.RunPython(seed_parking_slots, migrations.RunPython.noop),
    ]
