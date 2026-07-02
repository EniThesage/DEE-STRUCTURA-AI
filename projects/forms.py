from django import forms
from django.forms import inlineformset_factory

from .models import (
    ADDITIONAL_SERVICES_CHOICES, Project, ProjectDrawing, ProjectSpec, ReinforcementSpec, StructuralMember,
)

VALID_DRAWING_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp')


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'client_name', 'location', 'building_type']


class ProjectDrawingUploadForm(forms.ModelForm):
    class Meta:
        model = ProjectDrawing
        fields = ['file', 'discipline']

    def clean_file(self):
        file = self.cleaned_data['file']
        if not file.name.lower().endswith(VALID_DRAWING_EXTENSIONS):
            raise forms.ValidationError('Unsupported file type. Upload a PDF, JPG, PNG, or WEBP file.')
        return file


class ProjectSpecForm(forms.ModelForm):
    additional_services = forms.MultipleChoiceField(
        choices=ADDITIONAL_SERVICES_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = ProjectSpec
        exclude = ['project', 'updated_at']


class ReinforcementSpecForm(forms.ModelForm):
    class Meta:
        model = ReinforcementSpec
        fields = ['element', 'structural_member', 'bar_role', 'bar_size', 'spacing_mm']

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        project = project or getattr(self.instance, 'project', None)
        self.fields['structural_member'].queryset = (
            StructuralMember.objects.filter(project=project) if project is not None
            else StructuralMember.objects.none()
        )

        # Existing rows already know their element — narrow bar_role to the
        # valid pair server-side too, not just in the wizard's JS. New/empty
        # rows have no element yet, so the full set stays until the user
        # picks one (the JS narrows it live; clean() is the real backstop).
        if self.instance.element in ('column', 'beam'):
            valid_roles = ReinforcementSpec.COLUMN_BEAM_ROLES
        elif self.instance.element in ('foundation', 'slab'):
            valid_roles = ReinforcementSpec.SLAB_FOUNDATION_ROLES
        else:
            valid_roles = None
        if valid_roles is not None:
            self.fields['bar_role'].choices = [
                c for c in ReinforcementSpec.BAR_ROLE_CHOICES if c[0] in valid_roles
            ]


ReinforcementSpecFormSet = inlineformset_factory(
    Project,
    ReinforcementSpec,
    form=ReinforcementSpecForm,
    extra=1,
    can_delete=True,
)

StructuralMemberFormSet = inlineformset_factory(
    Project,
    StructuralMember,
    fields=['member_type', 'label', 'size', 'length_m', 'quantity_count'],
    extra=1,
    can_delete=True,
)


class ProjectFootprintForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['footprint_width_m', 'footprint_length_m']
