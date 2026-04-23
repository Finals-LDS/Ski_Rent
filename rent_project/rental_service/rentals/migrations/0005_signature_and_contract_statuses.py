from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0004_alter_rental_total_price_contract'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Расширяем статусы Contract
        migrations.AlterField(
            model_name='contract',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft',       'Черновик'),
                    ('sent',        'Отправлен'),
                    ('signed_card', 'Подписан через ЭЦП'),
                    ('signed_sms',  'Подписан через SMS'),
                    ('accepted',    'Принят'),
                    ('rejected',    'Отклонён'),
                ],
                default='draft',
                max_length=20,
            ),
        ),

        # 2. Создаём таблицу Signature
        migrations.CreateModel(
            name='Signature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('method', models.CharField(
                    choices=[('card', 'ЭЦП (карт-ридер / NCALayer)'), ('sms', 'SMS OTP')],
                    default='card',
                    max_length=10,
                    verbose_name='Способ подписания',
                )),
                ('raw_signature', models.TextField(verbose_name='Данные подписи (raw)')),
                ('signed_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата и время')),
                ('contract', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='signatures',
                    to='rentals.contract',
                    verbose_name='Договор',
                )),
                ('operator', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='signatures',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Оператор',
                )),
            ],
            options={
                'verbose_name': 'Подпись',
                'verbose_name_plural': 'Подписи',
                'ordering': ['-signed_at'],
            },
        ),
    ]
