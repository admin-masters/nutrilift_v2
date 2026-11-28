from django.conf import settings


def common(request):
    from .models import ProgrammeSettings
    user = getattr(request, 'user', None)
    return {
        'app_url': settings.PUBLIC_BASE_URL,
        'guide_config': ProgrammeSettings.get() if user and user.is_authenticated and user.role == 'teacher' else None,
    }
