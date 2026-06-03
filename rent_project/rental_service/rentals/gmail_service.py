"""Email sender через Django SMTP (Gmail App Password)."""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def send_email(to, subject, text_body, html_body=None, attachments=None):
    """
    to          : str или list[str]
    attachments : list of (filename, bytes, mimetype)
    """
    recipients = [to] if isinstance(to, str) else list(to)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    if html_body:
        msg.attach_alternative(html_body, "text/html")
    if attachments:
        for filename, data, mimetype in attachments:
            msg.attach(filename, data, mimetype)

    msg.send(fail_silently=False)
