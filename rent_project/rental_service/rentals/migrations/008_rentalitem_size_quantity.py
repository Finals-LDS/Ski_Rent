from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0007_smsotp')
    ]

    operations = [
        migrations.AddField(
            model_name='rentalitem',
            name='size',
            field=models.CharField(max_length=20, blank=True, default='', verbose_name='Размер'),
        ),
        migrations.AddField(
            model_name='rentalitem',
            name='quantity',
            field=models.PositiveIntegerField(default=1, verbose_name='Кол-во'),
        ),
    ]