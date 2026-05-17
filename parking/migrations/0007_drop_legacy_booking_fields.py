from django.db import migrations


def drop_legacy_booking_fields(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    statements = [
        "ALTER TABLE parking_parkingrequest DROP COLUMN IF EXISTS extension_count",
        "ALTER TABLE parking_parkingrequest DROP COLUMN IF EXISTS status_note",
        "ALTER TABLE parking_parkingrequest DROP COLUMN IF EXISTS auto_reassigned_at",
        "ALTER TABLE parking_parkingrequest DROP COLUMN IF EXISTS reassigned_from_slot_id",
        "ALTER TABLE parking_slotassignment DROP COLUMN IF EXISTS extension_count",
        "ALTER TABLE parking_slotassignment DROP COLUMN IF EXISTS source_request_id",
        "DROP TABLE IF EXISTS parking_bookingalert",
    ]

    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):

    dependencies = [
        ('parking', '0006_slotassignment_entered_at_vehiclescanlog'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_booking_fields, migrations.RunPython.noop),
    ]
