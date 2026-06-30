from urllib.parse import quote

from django.conf import settings
from django.shortcuts import render

from .forms import ContactForm


def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            if request.user.is_authenticated:
                message.submitted_by = request.user
            message.save()

            whatsapp_text = (
                f"New contact message from DEE STRUCTURA AI:\n"
                f"{message.get_title_display()} {message.name}\n"
                f"Company: {message.company_name or '-'}\n"
                f"Phone: {message.phone_number}\n"
                f"Email: {message.email}\n\n"
                f"{message.message}"
            )
            whatsapp_url = f"https://wa.me/{settings.WHATSAPP_BUSINESS_NUMBER}?text={quote(whatsapp_text)}"

            return render(request, 'core/contact_success.html', {'whatsapp_url': whatsapp_url})
    else:
        initial = {}
        if request.user.is_authenticated:
            initial = {
                'title': request.user.occupation,
                'name': request.user.name,
                'email': request.user.email,
            }
        form = ContactForm(initial=initial)

    return render(request, 'core/contact_form.html', {'form': form})
