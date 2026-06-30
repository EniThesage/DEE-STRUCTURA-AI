from django.conf import settings
from django.db import models

from accounts.models import OCCUPATION_CHOICES


class ContactMessage(models.Model):
    title = models.CharField(max_length=30, choices=OCCUPATION_CHOICES, default='other')
    name = models.CharField(max_length=150)
    email = models.EmailField()
    company_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=30)
    message = models.TextField()
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='contact_messages',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.created_at:%Y-%m-%d})'
