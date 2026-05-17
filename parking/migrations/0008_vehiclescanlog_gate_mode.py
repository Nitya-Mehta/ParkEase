from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('parking', '0007_drop_legacy_booking_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclescanlog',
            name='gate_mode',
            field=models.CharField(choices=[('entry', 'Entry'), ('exit', 'Exit')], default='entry', max_length=10),
        ),
    ]
