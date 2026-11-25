from datetime import date, timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from .models import ClassGroup, Screening, ProgrammeSettings, ReminderRun, User


def allowed_groups(user):
    groups = ClassGroup.objects.select_related('school')
    if user.role == 'programme':
        return groups.all()
    if user.role == 'principal':
        return groups.filter(school=user.school)
    return groups.filter(teachers=user)


def allowed_screenings(user):
    return Screening.objects.filter(student__group__in=allowed_groups(user)).select_related('student__group__school', 'performed_by', 'message_opened_by')


def latest_screenings(queryset):
    latest = queryset.filter(student_id=OuterRef('student_id')).order_by('-screened_on', '-created_at', '-pk').values('pk')[:1]
    return queryset.filter(pk=Subquery(latest))


def metrics(qs, today=None):
    today = today or timezone.localdate()
    latest = latest_screenings(qs)
    # A later form outside a period also closes its predecessor's due task.
    current_ids = latest_screenings(Screening.objects.all()).values('pk')
    return {
        'students': qs.values('student_id').distinct().count(),
        'screenings': qs.count(),
        'flagged': latest.filter(result__in=['red', 'yellow']).count(),
        'opened': qs.filter(message_opened_at__isnull=False).count(),
        'pending': qs.filter(result__in=['red', 'yellow'], message_opened_at__isnull=True).count(),
        'due': latest.filter(pk__in=current_ids, next_screening__lte=today).count(),
    }


def metric_records(qs, metric, today=None):
    today = today or timezone.localdate()
    if metric == 'screenings':
        return qs
    if metric == 'pending':
        return qs.filter(result__in=['red', 'yellow'], message_opened_at__isnull=True)
    if metric == 'opened':
        return qs.filter(message_opened_at__isnull=False)
    latest = latest_screenings(qs)
    if metric == 'flagged':
        return latest.filter(result__in=['red', 'yellow'])
    if metric == 'due':
        return latest.filter(pk__in=latest_screenings(Screening.objects.all()).values('pk'), next_screening__lte=today)
    return latest


def next_school_day(day, config):
    weekdays = {int(n) for n in config.school_weekdays.split(',')}
    holidays = {d.strip() for d in config.holidays.splitlines()}
    for offset in range(1, 367):
        candidate = day + timedelta(days=offset)
        if candidate.weekday() in weekdays and candidate.isoformat() not in holidays:
            return candidate
    raise ValueError('No school day configured within one year.')


def run_reminders(day=None):
    day = day or timezone.localdate()
    config = ProgrammeSettings.get()
    sent = 0
    for teacher in User.objects.filter(role='teacher', is_active=True):
        qs = allowed_screenings(teacher).filter(student__academic_year=config.academic_year)
        pending = qs.filter(result__in=['red', 'yellow'], message_opened_at__isnull=True)
        due = latest_screenings(qs).filter(next_screening__lte=day)
        first_pending = any(next_school_day(s.screened_on, config) == day for s in pending)
        new_due = due.filter(next_screening=day).exists()
        last = ReminderRun.objects.filter(teacher=teacher).order_by('-day').first()
        school_day = day.weekday() in {int(n) for n in config.school_weekdays.split(',')} and day.isoformat() not in config.holidays.splitlines()
        weekly = school_day and (not last or (day - last.day).days >= 7)
        eligible_pending = any(next_school_day(s.screened_on, config) <= day for s in pending)
        if not (first_pending or new_due or (weekly and (eligible_pending or due.exists()))):
            continue
        with transaction.atomic():
            record, created = ReminderRun.objects.get_or_create(teacher=teacher, day=day, defaults={'pending_count': pending.count(), 'due_count': due.count()})
            if not created:
                continue
            send_mail('NutriLift follow-ups', f'You have {record.pending_count} parents to notify and {record.due_count} students due for re-screening.\nOpen your Teacher Dashboard: {settings.PUBLIC_BASE_URL}/dashboard/', settings.DEFAULT_FROM_EMAIL, [teacher.email])
            sent += 1
    return sent
