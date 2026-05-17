from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_user_parking_pass_uservehicle'),
        ('parking', '0009_alter_vehiclescanlog_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='parkingslot',
            name='vip_only',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='parkingrequest',
            name='is_auto_booked',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='parkingrequest',
            name='vehicle_plate_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='slotassignment',
            name='vehicle_plate_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.CreateModel(
            name='AutoBookingRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vehicle_plate_number', models.CharField(max_length=20)),
                ('weekdays', models.CharField(max_length=32)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('is_active', models.BooleanField(default=True)),
                ('last_generated_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('requested_slot', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='auto_booking_rules', to='parking.parkingslot')),
                ('user', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='auto_booking_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
