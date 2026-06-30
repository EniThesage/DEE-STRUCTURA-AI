from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User


@receiver(post_save, sender=User)
def send_welcome_email(sender, instance, created, **kwargs):
    if not created:
        return

    send_mail(
        subject='Welcome to DEE STRUCTURA AI',
        message=(
            f'Hi {instance.name or instance.email},\n\n'
            'Your DEE STRUCTURA AI account is ready. DEE STRUCTURA AI turns architectural floor plan '
            'uploads into a professional Bill of Quantities (BOQ) '
            'using AI-assisted quantity takeoff and live Nigerian material pricing.\n\n'
            f'Log in any time: {settings.SITE_URL}/accounts/login/\n\n'
            '— The DEE STRUCTURA AI Team'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[instance.email],
        fail_silently=True,
    )
