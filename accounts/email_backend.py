import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

RESEND_API_URL = 'https://api.resend.com/emails'


class ResendAPIBackend(BaseEmailBackend):
    """Sends mail via Resend's HTTPS REST API instead of SMTP.

    Outbound SMTP (port 587) is commonly blocked on residential networks,
    sandboxed dev environments, and several PaaS hosts — HTTPS (443) almost
    never is, so this is more reliable than Django's stock SMTP backend for
    the same Resend account.
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent_count = 0
        for message in email_messages:
            html_body = None
            for content, mimetype in getattr(message, 'alternatives', []):
                if mimetype == 'text/html':
                    html_body = content
                    break

            payload = {
                'from': message.from_email,
                'to': message.to,
                'subject': message.subject,
                'text': message.body,
            }
            if html_body:
                payload['html'] = html_body

            try:
                response = httpx.post(
                    RESEND_API_URL,
                    json=payload,
                    headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}'},
                    timeout=10,
                )
                response.raise_for_status()
                sent_count += 1
            except httpx.HTTPError:
                if not self.fail_silently:
                    raise

        return sent_count
