import csv
import hashlib
import io
import json
import secrets
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import SignInForm, SchoolRegistrationForm, TeacherRegistrationForm, ScreeningForm, SettingsForm
from .models import School, User, ClassGroup, Student, Screening, ScreeningRevision, ProgrammeSettings, LocalEmail, LoginAttempt
from .schema import LANGUAGES, label
from .scoring import evaluate
from .services import allowed_groups, allowed_screenings, latest_screenings, metrics, metric_records, run_reminders

METRICS = [('students', 'Students screened', 'Unique students this period'), ('screenings', 'Screenings completed', 'Includes re-screenings'), ('flagged', 'Red flagged students', 'Latest result is red or yellow'), ('opened', 'Parent messages opened', 'WhatsApp opened · delivery unverified'), ('pending', 'Parents to notify', 'Flagged screenings awaiting a message'), ('due', 'Re-screenings due', 'Due today or overdue')]


class SignInView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = SignInForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        email = request.POST.get('username', '').strip().lower()
        request.POST = request.POST.copy()
        request.POST['username'] = email
        key = hashlib.sha256((email + '|' + request.META.get('REMOTE_ADDR', '')).encode()).hexdigest()
        attempt, _ = LoginAttempt.objects.get_or_create(key=key)
        if timezone.now() - attempt.started_at > timedelta(minutes=15):
            attempt.count, attempt.started_at = 0, timezone.now()
        if attempt.count >= 10:
            form = self.get_form()
            form.add_error(None, 'Too many attempts. Please try again in 15 minutes.')
            return self.form_invalid(form)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 302:
            attempt.delete()
        else:
            attempt.count += 1
            attempt.save()
        return response


def home(request):
    return redirect('dashboard' if request.user.is_authenticated else 'login')


def register(request, token=None):
    school = get_object_or_404(School, invitation_token=token) if token else None
    form = (TeacherRegistrationForm if school else SchoolRegistrationForm)(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        password = secrets.token_urlsafe(12)
        with transaction.atomic():
            if not school:
                school = School.objects.create(name=data['school_name'], address=data['address'], state=data['state'].strip().title(), district=data['district'].strip().title(), city=data['city'].strip())
            user = User.objects.create_user(username=data['email'], email=data['email'], password=password, first_name=data['name'], school=school, role='teacher' if token else 'principal', accepted_terms_at=timezone.now())
            if token:
                group, _ = ClassGroup.objects.get_or_create(school=school, grade=data['grade'], section=data['section'])
                group.teachers.add(user)
            send_mail('Welcome to NutriLift — your sign-in details', f'Registration successful.\nSchool: {school.name}\nEmail: {user.email}\nTemporary password: {password}\nSign in: {settings.PUBLIC_BASE_URL}/login/\nPlease change your password from your account page.', settings.DEFAULT_FROM_EMAIL, [user.email])
        login(request, user)
        messages.success(request, 'Registration successful. Your sign-in credentials are in your local email outbox. Please change your temporary password.')
        return redirect('dashboard')
    return render(request, 'registration/register.html', {'form': form, 'school': school})


def filter_scope(request):
    config = ProgrammeSettings.get()
    qs = allowed_screenings(request.user).filter(student__academic_year=config.academic_year)
    groups = allowed_groups(request.user)
    filters = {k: request.GET.get(k, '').strip() for k in ['state', 'district', 'school', 'school_query', 'group', 'start', 'end', 'q', 'metric']}
    if request.user.role == 'teacher' and not filters['group'] and 'group' not in request.GET:
        filters['group'] = str(request.session.get('selected_group', '') or (groups.first().pk if groups.exists() else ''))
    for key, lookup in [('state', 'student__group__school__state'), ('district', 'student__group__school__district')]:
        if filters[key]:
            qs = qs.filter(**{lookup: filters[key]})
    for key, lookup in [('school', 'student__group__school_id'), ('group', 'student__group_id')]:
        if filters[key]:
            if filters[key].isdigit():
                qs = qs.filter(**{lookup: int(filters[key])})
            else:
                qs = qs.none()
    if filters['group'].isdigit() and groups.filter(pk=int(filters['group'])).exists():
        request.session['selected_group'] = int(filters['group'])
    for key, lookup in [('start', 'screened_on__gte'), ('end', 'screened_on__lte')]:
        if filters[key]:
            try:
                day = date.fromisoformat(filters[key])
                qs = qs.filter(**{lookup: day})
            except ValueError:
                messages.error(request, 'Use a valid date for the reporting period.')
                qs = qs.none()
    if filters['start'] and filters['end'] and filters['start'] > filters['end']:
        messages.error(request, 'The start date must be on or before the end date.')
        qs = qs.none()
    if filters['q']:
        qs = qs.filter(student__roll_number__icontains=filters['q'])
    if filters['school_query']:
        qs = qs.filter(student__group__school__name__icontains=filters['school_query'])
    return qs, groups, config, filters


@login_required
def dashboard(request):
    qs, groups, config, filters = filter_scope(request)
    totals = metrics(qs)
    cards = []
    for key, title, help_text in METRICS:
        query = dict(filters, metric=key)
        cards.append({'key': key, 'title': title, 'hint': help_text, 'value': totals[key], 'url': '?' + urlencode(query)})
    rows = metric_records(qs, filters['metric'])
    page = Paginator(rows, 20).get_page(request.GET.get('page'))
    current_ids = set(latest_screenings(Screening.objects.filter(student_id__in=[s.student_id for s in page])).values_list('id', flat=True))
    for s in page:
        s.is_due = s.pk in current_ids and s.next_screening <= timezone.localdate()
    schools = School.objects.all() if request.user.role == 'programme' else School.objects.filter(pk=request.user.school_id)
    if filters['state']:
        schools = schools.filter(state=filters['state'])
    if filters['district']:
        schools = schools.filter(district=filters['district'])
    if filters['school_query']:
        schools = schools.filter(name__icontains=filters['school_query'])
    selected = groups.filter(pk=int(filters['group'])).first() if filters['group'].isdigit() else None
    breakdown = []
    if request.user.role == 'programme':
        # District -> school -> class drilldown, retaining the selected period.
        if filters['school'].isdigit():
            for g in groups.filter(school_id=int(filters['school'])):
                breakdown.append({'label': str(g), 'totals': metrics(qs.filter(student__group=g)), 'url': '?' + urlencode(dict(filters, group=g.pk))})
        elif filters['district']:
            for school in schools:
                breakdown.append({'label': school.name, 'sub': school.city, 'totals': metrics(qs.filter(student__group__school=school)), 'url': '?' + urlencode(dict(filters, school=school.pk, group=''))})
        else:
            for district in schools.values_list('district', flat=True).distinct().order_by('district'):
                breakdown.append({'label': district, 'totals': metrics(qs.filter(student__group__school__district=district)), 'url': '?' + urlencode(dict(filters, district=district, school='', group=''))})
    elif request.user.role == 'principal' and not selected:
        for g in groups:
            breakdown.append({'label': str(g), 'totals': metrics(qs.filter(student__group=g)), 'url': '?' + urlencode(dict(filters, group=g.pk))})
    return render(request, 'core/dashboard.html', {'config': config, 'filters': filters, 'cards': cards, 'page': page, 'groups': groups, 'schools': schools, 'states': School.objects.order_by('state').values_list('state', flat=True).distinct() if request.user.role == 'programme' else [], 'districts': School.objects.order_by('district').values_list('district', flat=True).distinct() if request.user.role == 'programme' else [], 'selected_group': selected, 'breakdown': breakdown, 'query': urlencode(filters), 'metric_title': dict((k, t) for k, t, _ in METRICS).get(filters['metric'], 'Student records'), 'today': timezone.localdate()})


@login_required
def export_records(request):
    qs, _, _, filters = filter_scope(request)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="nutrilift-screenings.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['School', 'State', 'District', 'Academic year', 'Class', 'Section', 'Roll number', 'Screening date', 'Result', 'WhatsApp opened', 'Next screening'])
    def safe(value):
        value = str(value)
        return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
    for s in metric_records(qs, filters['metric']):
        group = s.student.group
        writer.writerow([safe(v) for v in [group.school.name, group.school.state, group.school.district, s.student.academic_year, group.grade, group.section, s.student.roll_number, s.screened_on, s.result, s.message_opened_at or '', s.next_screening]])
    return response


@login_required
def screening_form(request, group_id=None, screening_id=None, student_id=None):
    if request.user.role != 'teacher':
        raise PermissionDenied
    original = get_object_or_404(allowed_screenings(request.user), pk=screening_id) if screening_id else None
    student = original.student if original else get_object_or_404(Student, pk=student_id, group__in=allowed_groups(request.user)) if student_id else None
    group = student.group if student else get_object_or_404(allowed_groups(request.user), pk=group_id)
    config = ProgrammeSettings.get()
    today = timezone.localdate()
    if student and student.academic_year != config.academic_year:
        raise PermissionDenied('This academic year is closed.')
    latest = student.screenings.first() if student else None
    if student and not original and latest and latest.next_screening > today:
        messages.info(request, 'The next screening is not due yet. Use Edit responses to correct an earlier form.')
        return redirect('student', student_id=student.pk)
    initial = dict(original.answers, roll_number=student.roll_number, revision=original.revision, submission_key=uuid.uuid4()) if original else {'submission_key': uuid.uuid4()}
    if student:
        initial['roll_number'] = student.roll_number
    language = request.GET.get('language', 'English')
    if language not in LANGUAGES:
        language = 'English'
    form = ScreeningForm(request.POST or None, initial=initial, day=original.screened_on if original else today, editing=bool(original), language=language)
    if student:
        form.fields['roll_number'].disabled = True
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if original:
                original = Screening.objects.select_for_update().get(pk=original.pk)
                if form.cleaned_data['revision'] != original.revision:
                    form.add_error(None, 'This form was changed in another window. Reload it before editing to avoid overwriting those changes.')
                else:
                    ScreeningRevision.objects.create(screening=original, changed_by=request.user, reason=form.cleaned_data['correction_reason'], previous={'answers': original.answers, 'result': original.result, 'findings': original.findings, 'next_screening': original.next_screening.isoformat(), 'revision': original.revision, 'message_opened_at': original.message_opened_at.isoformat() if original.message_opened_at else None})
                    original.answers = form.answers()
                    for k, v in evaluate(original.answers, original.screened_on).items():
                        setattr(original, k, v)
                    original.revision += 1
                    original.save()
                    messages.success(request, 'Responses corrected. The original screening date and message history are preserved.')
                    return redirect('screening', screening_id=original.pk)
            else:
                existing = Screening.objects.filter(submission_key=form.cleaned_data['submission_key']).first()
                if existing:
                    if existing.performed_by_id != request.user.pk or existing.student.group_id != group.pk:
                        raise PermissionDenied
                    return redirect('screening', screening_id=existing.pk)
                student, _ = Student.objects.get_or_create(group=group, academic_year=config.academic_year, roll_number=form.cleaned_data['roll_number'])
                latest = student.screenings.first()
                if latest and latest.next_screening > today:
                    form.add_error('roll_number', 'This student already has a screening and is not due yet. Open the student record to edit responses.')
                else:
                    answers = form.answers()
                    saved = Screening.objects.create(student=student, performed_by=request.user, answers=answers, submission_key=form.cleaned_data['submission_key'], **evaluate(answers, today))
                    messages.success(request, 'Screening saved successfully.')
                    return redirect('screening', screening_id=saved.pk)
    return render(request, 'core/screening_form.html', {'form': form, 'group': group, 'original': original, 'student': student, 'config': config, 'languages': LANGUAGES, 'language': language, 'screened_on': original.screened_on if original else today})


@login_required
def student_detail(request, student_id):
    student = get_object_or_404(Student.objects.select_related('group__school'), pk=student_id, group__in=allowed_groups(request.user))
    screenings = student.screenings.select_related('performed_by')
    latest = screenings.first()
    return render(request, 'core/student.html', {'student': student, 'screenings': screenings, 'latest': latest, 'is_due': latest and latest.next_screening <= timezone.localdate()})


@login_required
def screening_detail(request, screening_id):
    screening = get_object_or_404(allowed_screenings(request.user), pk=screening_id)
    rows = [{'label': label(key), 'value': str(value).replace('_', ' ').capitalize()} for key, value in screening.answers.items()]
    revisions = []
    for r in screening.revisions.select_related('changed_by').order_by('-changed_at'):
        revisions.append({'record': r, 'rows': [{'label': label(k), 'value': v} for k, v in r.previous['answers'].items()]})
    return render(request, 'core/screening_detail.html', {'screening': screening, 'rows': rows, 'revisions': revisions})


@login_required
def notify_parent(request, screening_id):
    if request.user.role != 'teacher':
        raise PermissionDenied
    screening = get_object_or_404(allowed_screenings(request.user), pk=screening_id, result__in=['red', 'yellow'])
    config = ProgrammeSettings.get()
    group = screening.student.group
    translations = {'Severe thinness': 'अतिशय कमी बीएमआय', 'Thinness': 'कमी बीएमआय', 'Obesity': 'लठ्ठपणाशी संबंधित बीएमआय', 'Overweight': 'जास्त वजनाशी संबंधित बीएमआय'}
    findings = []
    for f in screening.findings:
        if f['key'] == 'bmi':
            findings.append(translations[f['label']])
        else:
            findings.append(label(f['key'], 'Marathi'))
    payload = {'template': config.red_message if screening.result == 'red' else config.yellow_message, 'values': {'school': group.school.name, 'class': str(group.grade), 'section': group.section, 'roll': screening.student.roll_number, 'findings': '; '.join(findings), 'next_date': screening.next_screening.strftime('%d/%m/%Y'), 'video': config.red_video_url if screening.result == 'red' else config.yellow_video_url}, 'record_url': reverse('mark_opened', args=[screening.pk]), 'return_url': reverse('screening', args=[screening.pk])}
    return render(request, 'core/notify.html', {'screening': screening, 'payload': payload, 'config': config})


@login_required
@require_POST
def mark_opened(request, screening_id):
    if request.user.role != 'teacher':
        raise PermissionDenied
    # Parent details are never accepted by any endpoint.
    if request.body not in (b'', b'{}'):
        return JsonResponse({'error': 'This endpoint accepts no contact data.'}, status=400)
    with transaction.atomic():
        s = get_object_or_404(allowed_screenings(request.user).select_for_update(), pk=screening_id)
        if s.result == 'green':
            return JsonResponse({'error': 'No parent message is required.'}, status=409)
        if not s.message_opened_at:
            s.message_opened_at, s.message_opened_by = timezone.now(), request.user
            s.save(update_fields=['message_opened_at', 'message_opened_by'])
    return JsonResponse({'status': 'Parent notified', 'delivery_verified': False})


@login_required
def invite(request):
    if request.user.role != 'principal':
        raise PermissionDenied
    school = request.user.school
    url = settings.PUBLIC_BASE_URL + reverse('teacher_register', args=[school.invitation_token])
    guide_url = settings.PUBLIC_BASE_URL + reverse('guide')
    invitation = f'Hello, please register as a class teacher for the NutriLift School Screening Programme at {school.name}. Choose your class and section when you register. We’ll email your login details.\nRegister here: {url}\nHow to screen students: {guide_url}'
    return render(request, 'core/invite.html', {'school': school, 'invitation': invitation, 'invitation_url': url})


@login_required
def school_team(request):
    if request.user.role != 'principal':
        raise PermissionDenied
    form = TeacherRegistrationForm()
    if request.method == 'POST':
        teacher = get_object_or_404(User, pk=request.POST.get('teacher_id'), school=request.user.school, role='teacher')
        grade, section = request.POST.get('grade', ''), request.POST.get('section', '').strip().upper()
        import re
        if not grade.isdigit() or not 1 <= int(grade) <= 12 or not re.fullmatch(r'[A-Z0-9]{1,12}', section):
            messages.error(request, 'Choose a class from 1–12 and a valid section.')
        else:
            group, _ = ClassGroup.objects.get_or_create(school=request.user.school, grade=int(grade), section=section)
            if request.POST.get('action') == 'remove':
                group.teachers.remove(teacher)
                messages.success(request, 'Class access removed.')
            else:
                group.teachers.add(teacher)
                messages.success(request, 'Class access added.')
        return redirect('team')
    return render(request, 'core/team.html', {'teachers': User.objects.filter(school=request.user.school, role='teacher').prefetch_related('class_groups'), 'grades': range(1, 13)})


def guide(request):
    return render(request, 'core/guide.html', {'config': ProgrammeSettings.get()})


def guide_pdf(request):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph('NutriLift - Screening quick guide', styles['Title']), Spacer(1, 18)]
    for title, body in [('1. Identify the student', 'Confirm the school, academic year, class, section and roll number. Do not enter student names.'), ('2. Measure growth', 'Use a digital weighing scale and a stadiometer. Remove shoes and heavy jackets. Enter weight in kg and height in cm. For children under 60 months, record the MUAC tape colour. BMI-for-age is calculated from 60 months.'), ('3. Ask each question', 'Complete the health, diet, deworming and food-security questions. Ask adolescent girls sensitive questions discreetly. Use the observation periods stated in the form.'), ('4. Review the result', 'Any red finding produces a red result. Yellow findings without red produce yellow. Otherwise the result is green. The screening result is a referral prompt, not a diagnosis.'), ('5. Follow up', 'Red and yellow results require a parent message and re-screening in 3 calendar months. Green results require re-screening in 6 calendar months. Enter parent contact details only in the WhatsApp preparation screen.'), ('6. Correct or re-screen', 'Edit responses to correct an existing form. The original date is retained and changes are audited. When re-screening is due, submit a new blank form from the student record.')]:
        story += [Paragraph(title, styles['Heading2']), Paragraph(body, styles['BodyText']), Spacer(1, 10)]
    story.append(Paragraph('Local quick guide derived from the supplied screening workbook. Configure the programme-approved guide and video in Programme settings.', styles['Italic']))
    SimpleDocTemplate(buffer).build(story)
    return HttpResponse(buffer.getvalue(), content_type='application/pdf', headers={'Content-Disposition': 'inline; filename="nutrilift-quick-guide.pdf"'})


@login_required
def programme_settings(request):
    if request.user.role != 'programme':
        raise PermissionDenied
    config = ProgrammeSettings.get()
    form = SettingsForm(request.POST or None, instance=config)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Programme content settings saved.')
        return redirect('settings')
    return render(request, 'core/settings.html', {'form': form, 'config': config})


@login_required
def outbox(request):
    emails = LocalEmail.objects.all() if request.user.role == 'programme' else LocalEmail.objects.filter(recipient=request.user.email)
    return render(request, 'core/outbox.html', {'emails': emails.order_by('-created_at')[:100]})


@login_required
@require_POST
def reminders(request):
    if request.user.role != 'programme':
        raise PermissionDenied
    count = run_reminders()
    messages.success(request, f'{count} reminder email(s) created in the local outbox.')
    return redirect('outbox')


def terms(request):
    return render(request, 'core/terms.html')


def health(request):
    ProgrammeSettings.objects.exists()
    return JsonResponse({'status': 'ok', 'database': 'sqlite', 'mode': 'local'})


def csrf_failure(request, reason=''):
    return render(request, 'core/csrf_failure.html', {'reason': reason}, status=403)
