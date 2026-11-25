from django.core.mail.backends.base import BaseEmailBackend


class LocalEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from .models import LocalEmail
        for message in email_messages:
            for recipient in message.to:
                LocalEmail.objects.create(recipient=recipient, subject=message.subject, body=message.body)
        return len(email_messages)
