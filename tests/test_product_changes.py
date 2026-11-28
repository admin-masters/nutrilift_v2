"""Review regressions: current records, class workflow and report navigation."""
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import ClassGroup, ProgrammeSettings, Screening, Student
from core.scoring import add_months
from core.services import metrics
from test_application import env, create_screening, payload, sample_answers

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('role', ['teacher', 'principal', 'admin'])
def test_focused_dashboard_navigation(env, role):
    create_screening(env)
    env['client'].force_login(env[role])
    response = env['client'].get('/dashboard/')
    html = response.content.decode()
    assert 'Student records use roll numbers.' in html
    for removed in ['Export CSV', 'Local preview', 'Local email outbox', 'href="/settings/"', 'href="/outbox/"']:
        assert removed not in html
    if role == 'teacher':
        assert 'Start screening a student' in html and 'data-guide-dialog' in html
        assert 'name="start"' not in html and 'name="end"' not in html
    elif role == 'principal':
        assert 'Share link with class teachers' in html
        assert 'name="start"' not in html and 'name="end"' not in html
    else:
        assert response.context['filters']['state'] == 'Maharashtra'
        assert not response.context['show_records']
        assert 'id="records"' not in html
        assert len(response.context['cards']) == 6
        assert 'name="start"' in html


def test_teacher_full_year_roll_list_and_remembered_class(env):
    for roll in ['11', '2', '1']:
        create_screening(env, roll=roll)
    response = env['client'].get('/dashboard/?start=2999-01-01&end=2000-01-01')
    assert [s.student.roll_number for s in response.context['page']] == ['1', '2', '11']
    assert not response.context['date_errors']
    second = ClassGroup.objects.create(school=env['school'], grade=7, section='B')
    second.teachers.add(env['teacher'])
    create_screening(env, group=second, roll='7')
    env['client'].get('/dashboard/', {'group': second.pk})
    response = env['client'].get('/dashboard/')
    assert response.context['selected_group'] == second
    assert [s.student.roll_number for s in response.context['page']] == ['7']


def test_flagged_includes_yellow_and_prioritises_pending(env):
    day = timezone.localdate()
    red = dict(sample_answers(day), pallor='yes')
    yellow = dict(sample_answers(day), deworming='unknown')
    create_screening(env, roll='1', answers=red, message_opened_at=timezone.now())
    create_screening(env, roll='2', answers=yellow)
    create_screening(env, roll='3')
    response = env['client'].get('/dashboard/?metric=flagged')
    assert [s.student.roll_number for s in response.context['page']] == ['2', '1']
    assert response.context['totals']['flagged'] == 2
    assert response.context['totals']['pending'] == 1
    assert b'1 parent message pending' in response.content


def test_roll_checked_before_questions_and_same_scope_only(env):
    url = reverse('screen_new', args=[env['group'].pk])
    initial = env['client'].get(url)
    assert initial.context['roll_form']['roll_number'].value() is None
    assert b'autofocus' in initial.content and b'name="weight"' not in initial.content
    create_screening(env, roll='12', group=env['other_group'])
    response = env['client'].get(url, {'roll_number': '0012'})
    assert response.context['form']['roll_number'].value() == '12'
    assert response.context['form']['dob'].value() is None
    assert b'readonly' in response.content
    current = create_screening(env)
    response = env['client'].get(url, {'roll_number': '0012'})
    assert response.context['previous'] == current
    assert b'View record' in response.content and b'Edit responses' in response.content
    assert reverse('rescreen', args=[current.student_id]).encode() not in response.content
    assert b'name="weight"' not in response.content
    # A previous academic year must not prevent a fresh current-year record.
    current.student.academic_year = '2024-2025'
    current.student.save()
    assert env['client'].get(url, {'roll_number': '12'}).context['form']['dob'].value() is None


def test_due_student_requires_explicit_rescreen_and_next_is_blank(env):
    day = add_months(timezone.localdate(), -4)
    old = create_screening(env, day=day, answers=dict(sample_answers(day), pallor='yes'))
    url = reverse('screen_new', args=[env['group'].pk])
    response = env['client'].get(url, {'roll_number': '12'})
    assert response.context['is_due']
    assert reverse('rescreen', args=[old.student_id]).encode() in response.content
    response = env['client'].post(url, payload())
    assert response.status_code == 200 and Screening.objects.count() == 1
    assert b'choose Re-screen' in response.content
    response = env['client'].post(reverse('rescreen', args=[old.student_id]), payload())
    assert response.status_code == 302 and Screening.objects.count() == 2
    detail = env['client'].get(response.url)
    assert b'Screen next student' in detail.content
    next_form = env['client'].get(url)
    assert next_form.context['roll_form']['roll_number'].value() is None
    assert next_form.context['group'] == env['group']
    assert b'name="dob"' not in next_form.content


def test_new_screening_closes_older_pending_and_due_tasks(env):
    day = add_months(timezone.localdate(), -4)
    old = create_screening(env, day=day, answers=dict(sample_answers(day), pallor='yes'))
    current = create_screening(env)
    assert old.student_id == current.student_id
    assert metrics(Screening.objects.all()) == dict(students=1, screenings=2, flagged=0, opened=0, pending=0, due=0)
    assert env['client'].get(reverse('notify', args=[old.pk])).status_code == 302
    assert env['client'].post(reverse('mark_opened', args=[old.pk]), '{}', content_type='application/json').status_code == 409
    response = env['client'].get(reverse('student', args=[old.student_id]))
    assert response.context['latest'] == current
    assert not response.context['is_due']
    assert len(response.context['screenings']) == 2


def test_notify_cancel_is_readonly_and_reopen_preserves_date_and_count(env):
    s = create_screening(env, answers=dict(sample_answers(timezone.localdate()), pallor='yes'))
    return_url = '/dashboard/?' + urlencode({'group': env['group'].pk, 'metric': 'flagged'})
    notify_url = reverse('notify', args=[s.pk]) + '?' + urlencode({'return_to': return_url})
    page = env['client'].get(notify_url)
    assert page.context['payload']['return_url'] == return_url
    assert not page.context['payload']['ready']
    assert b'id="parent-name"' in page.content and b'id="parent-phone"' in page.content
    assert b'message-preview' not in page.content
    env['client'].get(return_url)  # Cancel never posts an opened event.
    s.refresh_from_db()
    assert s.message_opened_at is None
    mark = reverse('mark_opened', args=[s.pk])
    assert env['client'].post(mark, '{}', content_type='application/json').json()['status'] == 'Opened in WhatsApp'
    s.refresh_from_db()
    first_open, due = s.message_opened_at, s.next_screening
    env['client'].post(mark, '{}', content_type='application/json')
    s.refresh_from_db()
    assert (s.message_opened_at, s.next_screening) == (first_open, due)
    assert metrics(Screening.objects.all())['opened'] == 1


def test_programme_browse_and_exact_report_return(env):
    for n in range(22):
        create_screening(env, roll=str(n + 1))
    env['client'].force_login(env['admin'])
    response = env['client'].get('/dashboard/')
    assert 'Pune' in [row['label'] for row in response.context['breakdown']]
    response = env['client'].get('/dashboard/?district=Pune')
    assert response.context['breakdown'][0]['sub'] == 'Pune'
    response = env['client'].get(response.context['breakdown'][0]['url'])
    assert response.context['breakdown'][0]['label'] == str(env['group'])
    params = dict(state='Maharashtra', district='Pune', school=env['school'].pk, group=env['group'].pk,
                  start=(timezone.localdate() - timedelta(days=1)).isoformat(), end=timezone.localdate().isoformat(), metric='students', page=2)
    response = env['client'].get('/dashboard/', params)
    expected = response.context['report_url']
    record = list(response.context['page'])[0]
    history = env['client'].get(record.student_url)
    assert history.context['return_url'] == expected
    detail = env['client'].get(record.detail_url)
    assert detail.context['return_url'] == expected
    returned = env['client'].get(detail.context['return_url'])
    assert returned.context['page'].number == 2
    assert dict(parse_qs(urlsplit(expected).query)) == {k: [str(v)] for k, v in params.items()}


def test_invalid_dates_preserve_last_valid_report_and_page(env):
    create_screening(env)
    create_screening(env, group=env['other_group'])
    env['client'].force_login(env['admin'])
    valid = env['client'].get('/dashboard/', {'district': 'Pune', 'group': env['group'].pk})
    invalid = env['client'].get('/dashboard/', {'district': 'Nashik', 'start': '2026-12-31', 'end': '2026-01-01'})
    assert invalid.context['totals'] == valid.context['totals']
    assert invalid.context['filters'] == valid.context['filters']
    assert invalid.context['form_filters']['end'] == '2026-01-01'
    assert 'end' in invalid.context['date_errors']
    assert b'aria-describedby="end-error"' in invalid.content
    assert [s.pk for s in invalid.context['page']] == [s.pk for s in valid.context['page']]


def test_invalid_first_report_uses_real_default_totals(env):
    create_screening(env)
    env['client'].force_login(env['admin'])
    response = env['client'].get('/dashboard/?start=bad&end=also-bad')
    assert response.context['totals']['students'] == 1
    assert set(response.context['date_errors']) == {'start', 'end'}


@pytest.mark.parametrize('unsafe', ['https://other.example/dashboard/', '//other.example/dashboard/', '/settings/', '/dashboard/?' + '&'.join(f'a{i}=1' for i in range(31))])
def test_return_link_cannot_leave_report(env, unsafe):
    s = create_screening(env)
    response = env['client'].get(reverse('screening', args=[s.pk]), {'return_to': unsafe})
    assert response.context['return_url'] == f'/dashboard/?group={env["group"].pk}'


def test_invitation_contains_join_link_and_configured_guide(env):
    config = ProgrammeSettings.get()
    config.guide_url = 'https://example.org/approved-guide.pdf'
    config.save()
    env['client'].force_login(env['principal'])
    response = env['client'].get('/invite/')
    invitation = response.context['invitation']
    assert str(env['school'].invitation_token) in invitation
    assert config.guide_url in invitation
    assert b'Copy invitation' in response.content and b'Share via WhatsApp' in response.content
