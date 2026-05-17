from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_profile_picture'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='assigned_area',
            field=models.CharField(blank=True, choices=[('Thaltej', 'Thaltej'), ('Navrangpura', 'Navrangpura'), ('Paldi', 'Paldi'), ('Kalupur', 'Kalupur')], max_length=20, null=True),
        ),
    ]
