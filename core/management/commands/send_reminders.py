import time
from datetime import date
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.services import run_reminders


class Command(BaseCommand):
    help = 'Create due reminder emails in the local outbox. Idempotent per teacher/day.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat)
        parser.add_argument('--loop', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            sent = run_reminders(options['date'])
            if sent or not options['loop']:
                self.stdout.write(f'{sent} reminder email(s) created.')
            if not options['loop']:
                break
            time.sleep(60)
