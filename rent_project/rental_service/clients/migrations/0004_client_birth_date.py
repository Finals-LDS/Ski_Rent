from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0003_alter_client_document_id_alter_client_email_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='birth_date',
            field=models.DateField(blank=True, null=True, verbose_name='Дата рождения'),
        ),
        migrations.AddField(
            model_name='client',
            name='birthday_email_sent_year',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
