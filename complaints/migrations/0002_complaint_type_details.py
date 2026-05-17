from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('complaints', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='complaint',
            name='complaint_type',
            field=models.CharField(
                choices=[
                    ('Parking spot occupied', 'Parking spot occupied'),
                    ('Vehicle blocking access', 'Vehicle blocking access'),
                    ('Parking area damage', 'Parking area damage'),
                    ('Poor lighting or security issue', 'Poor lighting or security issue'),
                    ('Other', 'Other'),
                ],
                default='Parking spot occupied',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='complaint',
            name='complaint_details',
            field=models.TextField(blank=True),
        ),
    ]
