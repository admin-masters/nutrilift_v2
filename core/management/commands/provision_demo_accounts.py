import getpass
import hashlib
import sys

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import ClassGroup, LoginAttempt, School, User


ACCOUNTS = (
    ('teacher@nutrilift.local', 'teacher', 'Meera'),
    ('principal@nutrilift.local', 'principal', 'Anita Deshmukh'),
    ('admin@nutrilift.local', 'programme', 'Programme Admin'),
)


class Command(BaseCommand):
    help = 'Create or repair the three demo accounts and their school/class access without replacing existing data.'

    def add_arguments(self, parser):
        parser.add_argument('--password-stdin', action='store_true', help='Read the password from stdin instead of prompting.')
        parser.add_argument('--reset-passwords', action='store_true', help='Explicitly reset passwords for existing demo accounts.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['password_stdin']:
            password = sys.stdin.read().rstrip('\r\n')
        else:
            password = getpass.getpass('Demo account password: ')
            if password != getpass.getpass('Confirm password: '):
                raise CommandError('Passwords do not match.')
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from error

        existing = {}
        schools = {}
        for email, _, _ in ACCOUNTS:
            matches = list(User.objects.select_related('school').filter(Q(email__iexact=email) | Q(username__iexact=email)))
            if len(matches) > 1:
                raise CommandError(f'Conflicting username/email records for {email}; resolve them before provisioning.')
            if matches:
                user = matches[0]
                if user.email and user.email.lower() != email:
                    raise CommandError(f'The username {email} belongs to another email; no accounts changed.')
                if user.school_id:
                    if not user.school.is_demo:
                        raise CommandError(f'{email} is linked to a non-demo school; no accounts changed.')
                    if email != 'admin@nutrilift.local':
                        schools[user.school_id] = user.school
                existing[email] = user
        if len(schools) > 1:
            raise CommandError('The teacher and principal belong to different demo schools; resolve their assignments first.')
        school = next(iter(schools.values()), None)
        if school is None:
            school = School.objects.filter(name='Vidya Mandir School (Demo)', is_demo=True).order_by('pk').first()
        if school is None:
            school = School.objects.create(
                name='Vidya Mandir School (Demo)', is_demo=True, district='Pune', city='Pune',
                address='Fictional school for application testing',
            )

        teacher = None
        for email, role, name in ACCOUNTS:
            user = existing.get(email) or User(username=email, email=email)
            created = user.pk is None
            user.username = user.email = email
            user.role = role
            user.is_active = True
            user.school = None if role == 'programme' else school
            user.first_name = user.first_name or name
            user.accepted_terms_at = user.accepted_terms_at or timezone.now()
            if created or options['reset_passwords']:
                validate_password(password, user)
                user.set_password(password)
            user.save()
            if role == 'teacher':
                teacher = user
            self.stdout.write(f'{"Created" if created else "Updated"} {email} ({user.get_role_display()})')
        for section in ('A', 'B'):
            group, _ = ClassGroup.objects.get_or_create(school=school, grade=6, section=section)
            group.teachers.add(teacher)

        if options['reset_passwords']:
            # Clear only these IDs' failed attempts through local nginx ingress.
            # Other users and external IPs retain their rate-limit protection.
            keys = [hashlib.sha256(f'{email}|{address}'.encode()).hexdigest()
                    for email, _, _ in ACCOUNTS for address in ('127.0.0.1', '::1', '')]
            LoginAttempt.objects.filter(key__in=keys).delete()
        self.stdout.write(self.style.SUCCESS('Demo accounts ready. Teacher and principal share Class 6, Sections A and B.'))
