from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_assigned_area'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='parking_pass',
            field=models.CharField(
                choices=[('Free', 'Free Pass'), ('Pro', 'Pro Pass'), ('Premium', 'Premium Pass')],
                default='Free',
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name='UserVehicle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nickname', models.CharField(blank=True, max_length=40)),
                ('plate_number', models.CharField(max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='saved_vehicles', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='uservehicle',
            constraint=models.UniqueConstraint(fields=('user', 'plate_number'), name='unique_user_saved_vehicle'),
        ),
    ]
