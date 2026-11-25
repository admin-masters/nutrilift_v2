import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from core.models import User


class Command(BaseCommand):
    help = 'Provision an authorised SAPA/GOM account locally. Password is prompted, never passed as a shell argument.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', required=True)

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError(str(error))
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError('An account already uses this email.')
        user = User(username=email, email=email, first_name=options['name'], role='programme')
        password = getpass.getpass('Password: ')
        if password != getpass.getpass('Confirm password: '):
            raise CommandError('Passwords do not match.')
        try:
            validate_password(password, user)
        except ValidationError as error:
            raise CommandError(str(error))
        user.set_password(password)
        user.save()
        self.stdout.write(f'Programme account created for {email}.')
