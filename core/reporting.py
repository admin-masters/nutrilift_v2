"""Role-specific report scope and explicit navigation back to a report."""
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.urls import reverse

from .models import ProgrammeSettings
from .services import allowed_groups, allowed_screenings


FILTER_KEYS = ('state', 'district', 'school', 'school_query', 'group', 'start', 'end', 'q', 'metric')
METRIC_KEYS = ('students', 'screenings', 'flagged', 'opened', 'pending', 'due')


def report_link(filters=None, **changes):
    values = dict(filters or {}, **changes)
    query = urlencode({key: value for key, value in values.items() if key in (*FILTER_KEYS, 'page') and value})
    return reverse('dashboard') + ('?' + query if query else '')


def return_to_report(request, group_id=None):
    """Only accept our report route and known query parameters, never an external URL."""
    fallback = report_link(group=str(group_id)) if group_id else reverse('dashboard')
    candidate = request.POST.get('return_to') or request.GET.get('return_to', '')
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc or parsed.path != reverse('dashboard'):
            return fallback
        return report_link(dict(parse_qsl(parsed.query, max_num_fields=30)))
    except ValueError:
        return fallback


def record_link(name, pk, return_url):
    return reverse(name, args=[pk]) + '?' + urlencode({'return_to': return_url})


def report_scope(request, remember=True):
    config = ProgrammeSettings.get()
    groups = allowed_groups(request.user)
    filters = {key: request.GET.get(key, '').strip() for key in FILTER_KEYS}
    if filters['metric'] not in METRIC_KEYS:
        filters['metric'] = ''
    page = request.GET.get('page', '1')
    page = page if page.isdigit() and int(page) > 0 else '1'
    errors = {}
    form_filters = dict(filters)

    if request.user.role == 'programme':
        filters['state'] = form_filters['state'] = request.GET.get('state', 'Maharashtra').strip()
        dates = {}
        for key in ('start', 'end'):
            if filters[key]:
                try:
                    dates[key] = date.fromisoformat(filters[key])
                except ValueError:
                    errors[key] = 'Enter a valid date.'
        if not errors and dates.get('start') and dates.get('end') and dates['end'] < dates['start']:
            errors['end'] = 'End date must be on or after start date. The report below has not changed.'
        session_key = f'valid_report_{request.user.pk}'
        if errors:
            previous = request.session.get(session_key, {})
            filters = {key: previous.get(key, 'Maharashtra' if key == 'state' else '') for key in FILTER_KEYS}
            page = previous.get('page', '1')
        elif remember:
            request.session[session_key] = dict(filters, page=page)
    else:
        # School/class reporting covers the whole academic year, not a stale date range.
        for key in ('state', 'district', 'school', 'school_query', 'start', 'end'):
            filters[key] = ''
        if request.user.role == 'teacher':
            chosen = filters['group']
            if 'group' not in request.GET:
                chosen = str(request.session.get(f'class_{request.user.pk}', ''))
            selected = groups.filter(pk=int(chosen)).first() if chosen.isdigit() else None
            if selected is None:
                selected = groups.first()
            filters['group'] = str(selected.pk) if selected else ''
            if selected and remember:
                request.session[f'class_{request.user.pk}'] = selected.pk
        form_filters = dict(filters)

    qs = allowed_screenings(request.user).filter(student__academic_year=config.academic_year)
    for key, lookup in [('state', 'student__group__school__state'), ('district', 'student__group__school__district')]:
        if filters[key]:
            qs = qs.filter(**{lookup + '__iexact': filters[key]})
    for key, lookup in [('school', 'student__group__school_id'), ('group', 'student__group_id')]:
        if filters[key]:
            qs = qs.filter(**{lookup: int(filters[key])}) if filters[key].isdigit() else qs.none()
    for key, lookup in [('start', 'screened_on__gte'), ('end', 'screened_on__lte')]:
        if filters[key]:
            qs = qs.filter(**{lookup: date.fromisoformat(filters[key])})
    if filters['school_query']:
        qs = qs.filter(student__group__school__name__icontains=filters['school_query'])
    if filters['q']:
        qs = qs.filter(student__roll_number__icontains=filters['q'])
    return {
        'qs': qs, 'groups': groups, 'config': config, 'filters': filters,
        'form_filters': form_filters, 'date_errors': errors, 'page_number': page,
        'report_url': report_link(filters, page=page if page != '1' else ''),
    }
