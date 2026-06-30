from django import forms

from .models import ContactMessage


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['title', 'name', 'email', 'company_name', 'phone_number', 'message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 5}),
        }
