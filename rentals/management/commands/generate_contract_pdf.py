"""
Management command: python manage.py generate_contract_pdf <contract_id> [--out path.pdf]

Генерирует PDF договора и сохраняет на диск.
По умолчанию сохраняет в текущую папку как contract_<номер>.pdf.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rentals.models import Contract
from rentals.pdf_utils import generate_contract_pdf


class Command(BaseCommand):
    help = 'Сохраняет PDF договора на диск.'

    def add_arguments(self, parser):
        parser.add_argument(
            'contract_id',
            type=int,
            help='ID договора (Contract.id) для генерации PDF',
        )
        parser.add_argument(
            '--out',
            type=str,
            default=None,
            help='Путь, куда сохранить PDF (по умолчанию ./contract_<номер>.pdf)',
        )

    def handle(self, *args, **options):
        contract_id = options['contract_id']
        out_path = options['out']

        try:
            contract = Contract.objects.select_related('client', 'rental').get(
                pk=contract_id
            )
        except Contract.DoesNotExist:
            raise CommandError(f'Договор #{contract_id} не найден.')

        try:
            pdf_bytes = generate_contract_pdf(contract)
        except RuntimeError as exc:
            raise CommandError(str(exc))
        except Exception as exc:
            raise CommandError(f'Ошибка генерации PDF: {exc}')

        if not out_path:
            out_path = f'contract_{contract.rental.contract_number}.pdf'

        path = Path(out_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes)

        self.stdout.write(self.style.SUCCESS(
            f'✓ PDF договора #{contract_id} сохранён: {path} ({len(pdf_bytes)} байт)'
        ))
