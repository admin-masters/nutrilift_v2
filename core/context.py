from django.conf import settings


def common(request):
    return {'local_mode': True, 'app_url': settings.PUBLIC_BASE_URL}
