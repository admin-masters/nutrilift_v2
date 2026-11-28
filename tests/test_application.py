import json
import uuid
from datetime import date, timedelta
from unittest.mock import patch
import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from core.forms import ScreeningForm, SettingsForm
from core.models import School, ClassGroup, Student, Screening, User, ScreeningRevision, ProgrammeSettings, LocalEmail, ReminderRun
from core.scoring import evaluate, add_months, months_between, lms_z, bmi_flag, REFERENCE
from core.schema import HEALTH, DIET, WORKBOOK
from core.services import metrics, allowed_screenings, next_school_day, run_reminders
from core.management.commands.seed_demo import sample_answers

pytestmark = pytest.mark.django_db


@pytest.fixture
def env(client):
    school = School.objects.create(name='Test School', address='Test', state='Maharashtra', district='Pune', city='Pune')
    other = School.objects.create(name='Other School', address='Test', state='Maharashtra', district='Nashik', city='Nashik')
    teacher = User.objects.create_user(username='teacher@test.local', email='teacher@test.local', password='TestSecure@2026', first_name='Teacher', role='teacher', school=school)
    principal = User.objects.create_user(username='principal@test.local', email='principal@test.local', password='TestSecure@2026', first_name='Principal', role='principal', school=school)
    admin = User.objects.create_user(username='admin@test.local', email='admin@test.local', password='TestSecure@2026', first_name='Admin', role='programme')
    group = ClassGroup.objects.create(school=school, grade=6, section='A')
    group.teachers.add(teacher)
    other_group = ClassGroup.objects.create(school=other, grade=6, section='A')
    client.force_login(teacher)
    return dict(school=school, other=other, teacher=teacher, principal=principal, admin=admin, group=group, other_group=other_group, client=client)


def create_screening(env, day=None, answers=None, roll='12', group=None, **kwargs):
    day = day or timezone.localdate()
    answers = answers or sample_answers(day)
    student, _ = Student.objects.get_or_create(group=group or env['group'], academic_year=ProgrammeSettings.get().academic_year, roll_number=roll)
    return Screening.objects.create(student=student, performed_by=env['teacher'], screened_on=day, answers=answers, submission_key=uuid.uuid4(), **evaluate(answers, day), **kwargs)


def payload(day=None, **changes):
    day = day or timezone.localdate()
    return dict(sample_answers(day), roll_number='12', submission_key=str(uuid.uuid4()), **changes)


@pytest.mark.parametrize('day,months,expected', [(date(2026,7,10),3,date(2026,10,10)), (date(2026,7,10),6,date(2027,1,10)), (date(2026,11,30),3,date(2027,2,28)), (date(2023,11,30),3,date(2024,2,29)), (date(2026,8,31),6,date(2027,2,28))])
def test_calendar_month_due_dates(day, months, expected):
    assert add_months(day, months) == expected


@pytest.mark.parametrize('z,flag', [(-3.01,'red'),(-3,'yellow'),(-2.01,'yellow'),(-2,'green'),(1,'green'),(1.01,'yellow'),(2,'yellow'),(2.01,'red')])
def test_bmi_cutoff_boundaries(z, flag):
    assert bmi_flag(z)[0] == flag


@pytest.mark.parametrize('bmi,l,m,s,expected', [(30,-1.7862,16.9392,.11070,3.35),(14,-1.3529,20.4951,.12579,-3.80),(19,-1.6318,16.049,.10038,1.47)])
def test_who_published_worked_examples(bmi,l,m,s,expected):
    assert lms_z(bmi,l,m,s) == pytest.approx(expected,abs=.01)


def test_who_reference_complete_and_sex_specific():
    assert set(REFERENCE['male']) == {str(n) for n in range(60,229)}
    assert REFERENCE['male']['132'] != REFERENCE['female']['132']
    for sex in ['male','female']:
        for month, (l,m,s) in REFERENCE[sex].items():
            assert lms_z(m,l,m,s) == pytest.approx(0)


def test_eight_workbook_languages_preserved():
    assert set(WORKBOOK) == {'English','Hindi','Tamil','Malayalam','Kannada','Telugu','Marathi','Bengali'}
    for lang in WORKBOOK:
        assert '87' in WORKBOOK[lang]


@pytest.mark.parametrize('key,row,trigger', HEALTH)
def test_every_health_trigger(key,row,trigger):
    day=date(2026,11,24); a=sample_answers(day); a[key]=trigger
    result=evaluate(a,day)
    assert result['result']=='red'
    assert key in [f['key'] for f in result['findings']]


@pytest.mark.parametrize('key,row', DIET)
def test_every_diet_trigger(key,row):
    day=date(2026,11,24); a=sample_answers(day); a['diet_type']='nonveg'; a.update(egg='yes',meat='yes'); a[key]='yes' if key=='snacks' else 'no'
    result=evaluate(a,day)
    assert result['result']=='red'
    assert key in [f['key'] for f in result['findings']]


def test_yellow_red_priority_and_green():
    day=date(2026,11,24); a=sample_answers(day)
    assert evaluate(a,day)['result']=='green'
    a['deworming']='unknown'
    assert evaluate(a,day)['result']=='yellow'
    a['pallor']='yes'
    assert evaluate(a,day)['result']=='red'


def test_muac_under_five_and_exact_60_month_boundary():
    day=date(2026,11,24); a=sample_answers(day); a['dob']='2021-11-25';a['muac']='yellow'
    result=evaluate(a,day)
    assert result['age_months']==59 and result['bmi'] is None and result['result']=='yellow'
    a['dob']='2021-11-24'
    assert evaluate(a,day)['bmi'] is not None


def test_form_conditionals_required_and_stale_values_removed():
    data=payload(); data.update(egg='no',meat='no',menarche='yes',pads=10,clots='yes',muac='red')
    form=ScreeningForm(data)
    assert form.is_valid(),form.errors
    assert not {'egg','meat','menarche','pads','clots','muac'} & form.answers().keys()
    data['diet_type']='nonveg'; data.pop('egg')
    form=ScreeningForm(data)
    assert not form.is_valid() and 'egg' in form.errors


@pytest.mark.parametrize('key', ['dob','sex','weight','height','healthy','pallor','diet_type','breakfast','milk','deworming','food_security'])
def test_missing_required_answers(key):
    data=payload();data.pop(key)
    form=ScreeningForm(data)
    assert not form.is_valid() and key in form.errors


def test_adolescent_questions_and_menstrual_scoring():
    data=payload();data.update(sex='female',menarche='yes',menarche_age=10,pads=5,clots='yes',cycle='yes',bleeding_days=11)
    form=ScreeningForm(data);assert form.is_valid(),form.errors
    result=evaluate(form.answers(),timezone.localdate())
    assert {'pads','clots','cycle','bleeding_days'} <= {f['key'] for f in result['findings']}
    data.pop('pads');form=ScreeningForm(data);assert not form.is_valid() and 'pads' in form.errors
    data['menarche']='no';form=ScreeningForm(data);assert form.is_valid()
    assert 'clots' not in form.answers()


@pytest.mark.parametrize('change', [{'dob':'2999-01-01'},{'weight':0},{'height':0},{'sex':'other'},{'deworming':'bad'},{'roll_number':'<script>'}])
def test_invalid_input_rejected(change):
    data=payload();data.update(change);assert not ScreeningForm(data).is_valid()


def test_submission_idempotency_and_roll_normalisation(env):
    data=payload();data['roll_number']='0012'; url=reverse('screen_new',args=[env['group'].pk])
    first=env['client'].post(url,data);second=env['client'].post(url,data)
    assert first.status_code==302 and first.url==second.url
    assert Screening.objects.count()==1 and Student.objects.get().roll_number=='12'
    data['submission_key']=str(uuid.uuid4())
    response=env['client'].post(url,data)
    assert response.status_code==200 and Screening.objects.count()==1
    assert 'not due yet' in response.content.decode()


def test_isolation_same_roll_different_sections(env):
    first=create_screening(env)
    other=ClassGroup.objects.create(school=env['school'],grade=6,section='B')
    other.teachers.add(env['teacher'])
    second=create_screening(env,group=other)
    assert first.student_id != second.student_id
    assert metrics(allowed_screenings(env['teacher']))['students']==2


@pytest.mark.parametrize('role', ['teacher','principal'])
def test_cross_school_access_is_denied(env,role):
    s=create_screening(env,group=env['other_group'])
    env['client'].force_login(env[role])
    for name,args in [('screening',[s.pk]),('student',[s.student_id]),('screen_edit',[s.pk]),('notify',[s.pk]),('screen_new',[env['other_group'].pk])]:
        assert env['client'].get(reverse(name,args=args)).status_code in (403,404)
    assert env['client'].post(reverse('mark_opened',args=[s.pk]),'{}',content_type='application/json').status_code in (403,404)
    assert metrics(allowed_screenings(env[role]))['students']==0
    response=env['client'].get('/export/');assert 'Other School' not in response.content.decode()


def test_readonly_roles_cannot_change_screenings_or_notify(env):
    a=sample_answers(timezone.localdate());a['pallor']='yes';s=create_screening(env,answers=a)
    for role in ['principal','admin']:
        env['client'].force_login(env[role])
        assert env['client'].get(reverse('screening',args=[s.pk])).status_code==200
        assert env['client'].post(reverse('screen_edit',args=[s.pk]),payload()).status_code==403
        assert env['client'].post(reverse('mark_opened',args=[s.pk]),'{}',content_type='application/json').status_code==403


def test_edit_audit_original_date_message_history_and_stale_revision(env):
    day=timezone.localdate()-timedelta(days=40);a=sample_answers(day);a['pallor']='yes'
    s=create_screening(env,day=day,answers=a,message_opened_at=timezone.now(),message_opened_by=env['teacher'])
    data=dict(sample_answers(day),submission_key=str(uuid.uuid4()),roll_number='12',revision=1,correction_reason='Incorrect pallor answer')
    response=env['client'].post(reverse('screen_edit',args=[s.pk]),data)
    assert response.status_code==302
    s.refresh_from_db();assert s.result=='green' and s.screened_on==day and s.next_screening==add_months(day,6)
    assert s.message_opened_at and s.revision==2 and Screening.objects.count()==1
    assert ScreeningRevision.objects.get().previous['result']=='red'
    response=env['client'].post(reverse('screen_edit',args=[s.pk]),data)
    assert 'changed in another window' in response.content.decode()
    assert ScreeningRevision.objects.count()==1
    assert metrics(Screening.objects.all())['opened']==1


def test_pending_and_due_are_independent_and_reopening_counts_once(env):
    day=add_months(timezone.localdate(),-4);a=sample_answers(day);a['pallor']='yes';s=create_screening(env,day=day,answers=a)
    qs=Screening.objects.all();assert metrics(qs)['pending']==1 and metrics(qs)['due']==1
    url=reverse('mark_opened',args=[s.pk])
    for _ in range(2): assert env['client'].post(url,'{}',content_type='application/json').status_code==200
    totals=metrics(qs);assert totals['opened']==1 and totals['pending']==0 and totals['due']==1
    assert env['client'].post(url,json.dumps({'parent_name':'Secret Person','phone':'919999999999'}),content_type='application/json').status_code==400
    s.refresh_from_db();assert 'Secret Person' not in json.dumps(s.answers)


def test_rescreen_new_blank_form_and_historical_metrics(env):
    day=add_months(timezone.localdate(),-4);a=sample_answers(day);a['pallor']='yes';s=create_screening(env,day=day,answers=a)
    response=env['client'].get(reverse('rescreen',args=[s.student_id]));assert response.context['form']['dob'].value() is None
    response=env['client'].post(reverse('rescreen',args=[s.student_id]),payload());assert response.status_code==302
    totals=metrics(Screening.objects.all());assert totals=={'students':1,'screenings':2,'flagged':0,'opened':0,'pending':0,'due':0}
    assert metrics(Screening.objects.filter(screened_on=day))['flagged']==1
    assert metrics(Screening.objects.filter(screened_on=day))['due']==0


def test_registration_and_local_email(env):
    env['client'].logout()
    response=env['client'].post(reverse('teacher_register',args=[env['school'].invitation_token]),{'name':'New Teacher','email':'NEW@TEST.LOCAL','grade':5,'section':'b','terms':'on'})
    assert response.status_code==302
    user=User.objects.get(email='new@test.local');assert user.role=='teacher'
    assert user.class_groups.get().section=='B'
    assert LocalEmail.objects.filter(recipient=user.email).exists()
    assert user.accepted_terms_at


def test_principal_registration_and_terms(env):
    env['client'].logout()
    data={'name':'Principal Two','email':'newprincipal@test.local','school_name':'School Two','address':'123 road','state':'Maharashtra','district':'pune','city':'Pune'}
    assert env['client'].post('/register/',data).status_code==200
    assert not User.objects.filter(email=data['email']).exists()
    data['terms']='on';assert env['client'].post('/register/',data).status_code==302
    assert User.objects.get(email=data['email']).school.district=='Pune'


def test_outbox_access_and_settings_permissions(env):
    LocalEmail.objects.create(recipient=env['principal'].email,subject='Private principal email',body='private-body-marker')
    assert b'private-body-marker' not in env['client'].get('/outbox/').content
    assert env['client'].get('/settings/').status_code==403
    env['client'].force_login(env['admin']);assert b'private-body-marker' in env['client'].get('/outbox/').content
    assert env['client'].get('/settings/').status_code==200


def test_reminder_schedule_school_days_holidays_and_idempotency(env):
    config=ProgrammeSettings.get();config.holidays='2026-11-23';config.save()
    friday=date(2026,11,20);assert next_school_day(friday,config)==date(2026,11,24)
    a=sample_answers(friday);a['pallor']='yes';create_screening(env,day=friday,answers=a)
    assert run_reminders(friday)==0
    assert run_reminders(date(2026,11,23))==0
    assert run_reminders(date(2026,11,24))==1
    assert run_reminders(date(2026,11,24))==0
    assert run_reminders(date(2026,11,25))==0
    assert run_reminders(date(2026,12,1))==1
    assert LocalEmail.objects.count()==2 and ReminderRun.objects.count()==2


def test_no_csrf_no_mutation(env):
    c=Client(enforce_csrf_checks=True);c.force_login(env['teacher'])
    response=c.post(reverse('screen_new',args=[env['group'].pk]),payload())
    assert response.status_code==403 and Screening.objects.count()==0


def test_template_escape_csv_formula_and_all_pages(env):
    env['school'].name='=dangerous';env['school'].save();s=create_screening(env)
    for role in ['teacher','principal','admin']:
        env['client'].force_login(env[role])
        for path in ['/dashboard/','/dashboard/?metric=screenings','/dashboard/?metric=pending','/dashboard/?start=bad','/outbox/','/guide/','/terms/',reverse('screening',args=[s.pk]),reverse('student',args=[s.student_id])]:
            assert env['client'].get(path).status_code==200,path
    assert "'=dangerous" in env['client'].get('/export/').content.decode()
    assert env['client'].get('/guide/pdf/')['Content-Type']=='application/pdf'


def test_login_rate_limit(env):
    env['client'].logout()
    for _ in range(11): response=env['client'].post('/login/',{'username':env['teacher'].email,'password':'bad'})
    assert b'Too many attempts' in response.content


def test_settings_reject_bad_placeholders(env):
    config=ProgrammeSettings.get()
    form=SettingsForm({'red_message':'{parent.__class__}','yellow_message':'hello','school_weekdays':'0,1,2,3,4'},instance=config)
    assert not form.is_valid() and 'red_message' in form.errors


def test_security_headers_and_valid_csrf_login(env):
    c=Client(enforce_csrf_checks=True)
    response=c.get('/login/')
    assert response['Referrer-Policy']=='same-origin'
    assert response['Cache-Control']=='no-store, private'
    assert "default-src 'self'" in response['Content-Security-Policy']
    token=c.cookies['csrftoken'].value
    response=c.post('/login/',{'username':env['teacher'].email,'password':'TestSecure@2026','csrfmiddlewaretoken':token},HTTP_ORIGIN='http://testserver')
    assert response.status_code==302


def test_programme_school_search(env):
    create_screening(env);create_screening(env,group=env['other_group'])
    env['client'].force_login(env['admin'])
    response=env['client'].get('/dashboard/',{'school_query':'Other School'})
    assert response.context['cards'][0]['value']==1
    assert response.context['page'].object_list[0].student.group.school==env['other']


def test_teacher_access_grant_and_revocation(env):
    group=ClassGroup.objects.create(school=env['school'],grade=7,section='C')
    s=create_screening(env,group=group)
    assert env['client'].get(reverse('screening',args=[s.pk])).status_code==404
    env['client'].force_login(env['principal'])
    response=env['client'].post('/team/',{'teacher_id':env['teacher'].pk,'grade':7,'section':'C'})
    assert response.status_code==302
    env['client'].force_login(env['teacher'])
    assert env['client'].get(reverse('screening',args=[s.pk])).status_code==200
    env['client'].force_login(env['principal'])
    env['client'].post('/team/',{'teacher_id':env['teacher'].pk,'grade':7,'section':'C','action':'remove'})
    env['client'].force_login(env['teacher'])
    assert env['client'].get(reverse('screening',args=[s.pk])).status_code==404


def test_password_reset_email_and_new_password(env):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes
    env['client'].logout()
    response=env['client'].post('/password-reset/',{'email':env['teacher'].email})
    assert response.status_code==302
    email=LocalEmail.objects.get();assert '/reset/' in email.body
    token=default_token_generator.make_token(env['teacher'])
    uid=urlsafe_base64_encode(force_bytes(env['teacher'].pk))
    response=env['client'].get(f'/reset/{uid}/{token}/')
    assert response.status_code==302
    response=env['client'].post(response.url,{'new_password1':'ChangedSecure@2026','new_password2':'ChangedSecure@2026'})
    assert response.status_code==302
    env['teacher'].refresh_from_db();assert env['teacher'].check_password('ChangedSecure@2026')


def test_configured_resources_and_message_used(env):
    config=ProgrammeSettings.get()
    data={'guide_url':'https://example.org/guide.pdf','guide_video_url':'https://example.org/guide-video','red_video_url':'https://example.org/mr-red','yellow_video_url':'https://example.org/mr-yellow','red_message':'नमस्कार {parent} {findings} {video}','yellow_message':'नमस्कार {parent} {video}','content_approved':'on','school_weekdays':'0,1,2,3,4,5','holidays':'2026-12-25'}
    form=SettingsForm(data,instance=config);assert form.is_valid(),form.errors
    form.save()
    a=sample_answers(timezone.localdate());a['pallor']='yes';s=create_screening(env,answers=a)
    response=env['client'].get(reverse('notify',args=[s.pk]))
    assert response.context['payload']['values']['video']=='https://example.org/mr-red'
    assert response.context['payload']['template']==data['red_message']
    assert b'Local test content.' not in response.content


def test_due_date_reminder_and_calendar_boundaries(env):
    today=date(2026,11,24);day=date(2026,8,24)
    a=sample_answers(day);a['pallor']='yes'
    create_screening(env,day=day,answers=a,message_opened_at=timezone.now(),message_opened_by=env['teacher'])
    assert run_reminders(today-timedelta(days=1))==0
    assert run_reminders(today)==1
    assert '0 parents to notify and 1 students due' in LocalEmail.objects.get().body


def test_programme_account_provisioning():
    from django.core.management import call_command
    from django.core.management.base import CommandError
    with patch('getpass.getpass',return_value='AdditionalSecure@2026'):
        call_command('create_programme_user',email='official@example.org',name='Programme Official')
    user=User.objects.get(email='official@example.org')
    assert user.role=='programme' and user.check_password('AdditionalSecure@2026')
    with pytest.raises(CommandError):
        call_command('create_programme_user',email='official@example.org',name='Duplicate')
