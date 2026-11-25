import pytest


@pytest.fixture(autouse=True)
def local_email_backend(settings):
    # pytest-django defaults to locmem; exercise the actual local database outbox.
    settings.EMAIL_BACKEND = 'core.mail.LocalEmailBackend'
