from django import forms
from django.forms import modelformset_factory

from .models import BEMEDocument, BEMELineItem


class BEMELetterheadForm(forms.ModelForm):
    class Meta:
        model = BEMEDocument
        fields = [
            'letterhead_company', 'letterhead_address', 'letterhead_phone', 'letterhead_email',
            'letterhead_color', 'prepared_by', 'reference_number',
        ]
        widgets = {
            'letterhead_color': forms.TextInput(attrs={'type': 'color'}),
        }


class BEMELineItemForm(forms.ModelForm):
    class Meta:
        model = BEMELineItem
        fields = ['description', 'qty', 'unit', 'rate', 'amount']
        widgets = {
            'qty': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'rate': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('DELETE'):
            return cleaned

        description = cleaned.get('description')
        if self.instance.is_section_header or not description:
            return cleaned

        if self.instance.is_provisional_sum:
            if cleaned.get('amount') is None:
                self.add_error('amount', 'Enter an amount for this provisional sum.')
        elif cleaned.get('qty') is None or cleaned.get('rate') is None:
            self.add_error('qty', 'Enter both quantity and rate.')
        return cleaned


BEMELineItemFormSet = modelformset_factory(
    BEMELineItem,
    form=BEMELineItemForm,
    extra=2,
    can_delete=True,
)
