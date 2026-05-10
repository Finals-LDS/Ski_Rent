from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0007_alter_client_id_alter_equipment_id_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Client',
        ),
    ]
