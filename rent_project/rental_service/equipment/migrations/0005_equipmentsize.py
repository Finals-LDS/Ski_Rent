from django.db import migrations, models
import django.db.models.deletion 

class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0004_client_iin_client_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipment',
            name='has_sizes',
            field=models.BooleanField(default=False, verbose_name='Есть размеры'),
        ),
        migrations.CreateModel(
            name='EquipmentSize',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('size', models.CharField(max_length=20, verbose_name='Размер')),
                ('quantity', models.IntegerField(default=1, verbose_name='Кол-во')),
                ('quantity_rented', models.IntegerField(default=0, verbose_name='В аренде')),
                ('equipment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sizes', to='equipment.equipment')),
            ],
            options={
                'verbose_name': 'Размер',
                'verbose_name_plural': 'Размер',
                'unique_together': {('equipment', 'size')},
            },
        ),
    ]