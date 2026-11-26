import hashlib
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from core.models import ClassGroup, LoginAttempt, ProgrammeSettings, School, Screening, Student, User


pytestmark = pytest.mark.django_db
PASSWORD = 'NutriLift@2026'


@pytest.fixture(autouse=True)
def fast_test_passwords(settings):
    # Test account provisioning/authentication, not Django's hashing cost.
    # Production retains its normal password hashers.
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def provision(monkeypatch, password=PASSWORD, reset=False):
    output = StringIO()
    monkeypatch.setattr('sys.stdin', StringIO(password + '\n'))
    call_command('provision_demo_accounts', password_stdin=True, reset_passwords=reset, stdout=output)
    assert password not in output.getvalue()


@pytest.mark.parametrize('email,role', [
    ('teacher@nutrilift.local', 'teacher'),
    ('principal@nutrilift.local', 'principal'),
    ('admin@nutrilift.local', 'programme'),
])
def test_provisioned_accounts_can_use_real_login_form_and_role_pages(monkeypatch, email, role):
    provision(monkeypatch, reset=True)
    user = User.objects.get(email=email)
    assert user.role == role and user.is_active
    assert not user.is_superuser and not user.is_staff
    client = Client(enforce_csrf_checks=True)
    assert client.get('/login/').status_code == 200
    response = client.post('/login/', {
        'username': email, 'password': PASSWORD,
        'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
    })
    assert response.status_code == 302 and response.url == '/dashboard/'
    assert client.get('/dashboard/').status_code == 200
    assert client.get(reverse('settings')).status_code == (200 if role == 'programme' else 403)
    group = ClassGroup.objects.get(grade=6, section='A')
    assert client.get(reverse('screen_new', args=[group.pk])).status_code == (200 if role == 'teacher' else 403)
    if role == 'principal':
        assert client.get(reverse('team')).status_code == 200


def test_rerun_preserves_changed_passwords_and_does_not_duplicate_data(monkeypatch):
    provision(monkeypatch)
    teacher = User.objects.get(email='teacher@nutrilift.local')
    teacher.set_password('MyChangedPassword@2026')
    teacher.save()
    hashes = dict(User.objects.values_list('pk', 'password'))
    identities = list(User.objects.values_list('pk', 'school_id'))
    provision(monkeypatch, password='AnotherSecurePassword@2026')
    assert dict(User.objects.values_list('pk', 'password')) == hashes
    assert list(User.objects.values_list('pk', 'school_id')) == identities
    assert User.objects.count() == 3
    assert School.objects.count() == 1
    assert ClassGroup.objects.count() == 2
    assert teacher.class_groups.count() == 2


def test_repair_partial_accounts_and_clear_only_demo_proxy_lockouts(monkeypatch):
    teacher = User.objects.create_user(
        username='Teacher@NutriLift.Local', email='Teacher@NutriLift.Local',
        password='WrongPassword@2026', role='programme', is_active=False,
    )
    demo_key = hashlib.sha256(b'teacher@nutrilift.local|127.0.0.1').hexdigest()
    other_key = hashlib.sha256(b'other@example.org|127.0.0.1').hexdigest()
    LoginAttempt.objects.create(key=demo_key, count=10)
    LoginAttempt.objects.create(key=other_key, count=10)
    provision(monkeypatch, reset=True)
    teacher.refresh_from_db()
    assert teacher.username == teacher.email == 'teacher@nutrilift.local'
    assert teacher.check_password(PASSWORD) and teacher.is_active and teacher.role == 'teacher'
    assert teacher.school_id == User.objects.get(email='principal@nutrilift.local').school_id
    assert teacher.class_groups.count() == 2
    assert not LoginAttempt.objects.filter(key=demo_key).exists()
    assert LoginAttempt.objects.filter(key=other_key, count=10).exists()


def test_explicit_reset_preserves_existing_seeded_records_and_other_users(monkeypatch):
    call_command('seed_demo', stdout=StringIO())
    unrelated = User.objects.create_user(username='real@example.org', email='real@example.org', password='KeepThisPassword@2026', role='programme')
    original_hash = unrelated.password
    records = list(Screening.objects.values_list('pk', 'student_id', 'answers', 'result'))
    settings = ProgrammeSettings.get()
    settings.academic_year = '2027-2028'
    settings.save()
    original_counts = (School.objects.count(), ClassGroup.objects.count(), Student.objects.count())
    original_ids = dict(User.objects.values_list('email', 'pk'))
    provision(monkeypatch, reset=True)
    assert list(Screening.objects.values_list('pk', 'student_id', 'answers', 'result')) == records
    assert (School.objects.count(), ClassGroup.objects.count(), Student.objects.count()) == original_counts
    assert dict(User.objects.values_list('email', 'pk')) == original_ids
    assert ProgrammeSettings.get().academic_year == '2027-2028'
    unrelated.refresh_from_db()
    assert unrelated.password == original_hash


def test_conflicting_identities_abort_without_partial_changes(monkeypatch):
    User.objects.create_user(username='admin@nutrilift.local', email='another@example.org', role='programme')
    User.objects.create_user(username='another-login', email='admin@nutrilift.local', role='programme')
    with pytest.raises(CommandError, match='Conflicting'):
        provision(monkeypatch, reset=True)
    assert User.objects.count() == 2
    assert School.objects.count() == 0


def test_non_demo_school_assignment_is_not_overwritten(monkeypatch):
    school = School.objects.create(name='Existing real school', address='Existing', district='Pune', city='Pune')
    teacher = User.objects.create_user(username='teacher@nutrilift.local', email='teacher@nutrilift.local', role='teacher', school=school)
    with pytest.raises(CommandError, match='non-demo school'):
        provision(monkeypatch, reset=True)
    teacher.refresh_from_db()
    assert teacher.school_id == school.pk
    assert User.objects.count() == School.objects.count() == 1


def test_invalid_password_cannot_create_accounts(monkeypatch):
    with pytest.raises(CommandError):
        provision(monkeypatch, password='123')
    assert User.objects.count() == School.objects.count() == 0
