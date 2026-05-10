from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0010_alter_contract_id_alter_discount_id_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='SmsOTP',
        ),
    ]
