from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView

from beme.models import BEMEDocument

from .forms import (
    ProjectDrawingUploadForm, ProjectFootprintForm, ProjectForm, ProjectSpecForm, ReinforcementSpecFormSet,
    StructuralMemberFormSet,
)
from .models import Project, ProjectDrawing, Room
from .services import ExtractionError, extract_rooms_from_floor_plan

RoomFormSet = modelformset_factory(
    Room,
    fields=['name', 'width', 'length', 'door_count', 'window_count'],
    extra=1,
    can_delete=True,
)

# Both dimensions under this are almost certainly a structural post/store, not
# a room. Aspect ratio over this is almost certainly a dimension-line/corridor
# misread. Either way: excluded from Room creation, surfaced to the engineer
# via ProjectDrawing.extraction_flags instead of silently becoming a room.
MIN_ROOM_DIMENSION_M = Decimal('1.2')
MAX_ROOM_ASPECT_RATIO = 12
AREA_MISMATCH_WARNING_PCT = 40


def _safe_decimal(value):
    """The AI returns building_width_m/building_length_m as JSON numbers (or
    omits them) — convert defensively so a missing/odd value never breaks the
    rest of the upload, it just leaves the footprint fields blank."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'projects/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = Project.objects.filter(user=self.request.user)
        documents = BEMEDocument.objects.filter(project__in=projects)
        context['total_projects'] = projects.count()
        context['total_boqs'] = documents.count()
        context['total_estimated_value'] = sum((doc.contract_sum for doc in documents), Decimal('0'))
        context['recent_projects'] = projects[:5]
        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('projects:detail', kwargs={'pk': self.object.pk})


class ProjectDeleteView(LoginRequiredMixin, DeleteView):
    model = Project
    success_url = reverse_lazy('projects:dashboard')
    http_method_names = ['post']

    def get_queryset(self):
        return Project.objects.filter(user=self.request.user)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Project deleted.')
        return response


class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = 'projects/project_detail.html'
    context_object_name = 'project'

    def get_queryset(self):
        return Project.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['upload_form'] = ProjectDrawingUploadForm()
        context['drawings'] = self.object.drawings.all()
        context['rooms'] = self.object.rooms.all()
        context['spec'] = getattr(self.object, 'spec', None)
        return context


class ProjectDrawingUploadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        form = ProjectDrawingUploadForm(request.POST, request.FILES)

        if not form.is_valid():
            messages.error(request, 'Please upload a valid PDF, JPG, PNG, or WEBP file.')
            return redirect('projects:detail', pk=project.pk)

        drawing = form.save(commit=False)
        drawing.project = project

        # Only the architectural pass is wired up so far — other disciplines
        # are stored for reference so the schema/UI is ready when their
        # extraction passes land, rather than silently pretending to process them.
        if drawing.discipline != 'architectural':
            drawing.extraction_status = 'pending'
            drawing.notes = 'Automatic extraction for this discipline is not available yet — file stored for reference.'
            drawing.save()
            messages.info(
                request,
                f'{drawing.get_discipline_display()} drawing uploaded. Automatic extraction for this '
                'discipline is coming in a later update — the file is saved for reference.',
            )
            return redirect('projects:detail', pk=project.pk)

        drawing.extraction_status = 'processing'
        drawing.save()

        try:
            data = extract_rooms_from_floor_plan(drawing.file.path)
        except ExtractionError as exc:
            drawing.extraction_status = 'failed'
            drawing.extraction_error = str(exc)
            drawing.save()
            messages.warning(request, str(exc))
            return redirect('projects:detail', pk=project.pk)

        footprint_width = _safe_decimal(data.get('building_width_m'))
        footprint_length = _safe_decimal(data.get('building_length_m'))
        if footprint_width and footprint_length:
            project.footprint_width_m = footprint_width
            project.footprint_length_m = footprint_length
            project.save(update_fields=['footprint_width_m', 'footprint_length_m'])

        rooms_data = data.get('rooms', [])
        excluded_candidates = []
        created_count = 0
        for room in rooms_data:
            width = room.get('width_m') or 0
            length = room.get('length_m') or 0
            name = room.get('name') or 'Room'
            confidence = room.get('confidence') or 'medium'
            door_count = int(room.get('door_count') or 0)
            window_count = int(room.get('window_count') or 0)

            dims = sorted([_safe_decimal(width) or Decimal('0'), _safe_decimal(length) or Decimal('0')])
            if dims[1] > 0 and dims[1] < MIN_ROOM_DIMENSION_M:
                excluded_candidates.append({
                    'label': name,
                    'reason': 'both dimensions under 1.2m — possible structural post/store, not a room',
                })
                continue
            if dims[0] > 0 and (dims[1] / dims[0]) > MAX_ROOM_ASPECT_RATIO:
                excluded_candidates.append({
                    'label': name,
                    'reason': 'aspect ratio over 12:1 — possible corridor misread / dimension-line artifact',
                })
                continue

            Room.objects.create(
                project=project,
                source_drawing=drawing,
                name=name,
                width=width,
                length=length,
                door_count=door_count,
                window_count=window_count,
                confidence=confidence,
                is_manual=False,
            )
            created_count += 1

        area_mismatch_pct = None
        if footprint_width and footprint_length and footprint_width * footprint_length > 0:
            footprint_area = footprint_width * footprint_length
            total_room_area = sum(
                ((_safe_decimal(r.get('width_m')) or Decimal('0')) * (_safe_decimal(r.get('length_m')) or Decimal('0'))
                 for r in rooms_data),
                Decimal('0'),
            )
            area_mismatch_pct = abs(total_room_area - footprint_area) / footprint_area * 100

        drawing.extraction_flags = {
            'excluded_candidates': excluded_candidates,
            'external_works_noted': data.get('external_works_noted') or [],
            'area_mismatch_pct': float(area_mismatch_pct) if area_mismatch_pct is not None else None,
        }
        drawing.extraction_status = 'completed'
        drawing.save()

        notice = f'Extracted {created_count} rooms from the drawing.'
        if excluded_candidates:
            notice += (
                f' {len(excluded_candidates)} item(s) excluded as likely non-room elements '
                '(see notes on the Review Rooms page).'
            )
        if footprint_width and footprint_length:
            notice += f' Detected building footprint {footprint_width}m x {footprint_length}m — confirm it on the Review Rooms page.'
        else:
            notice += ' Could not detect an overall building footprint — enter it manually on the Review Rooms page for more accurate quantities.'
        extraction_notes = (data.get('extraction_notes') or '').strip()
        if extraction_notes:
            notice += f' Note: {extraction_notes}'
        messages.success(request, notice)
        return redirect('projects:detail', pk=project.pk)


class RoomReviewView(LoginRequiredMixin, View):
    """Doubles as the mandatory confirmation gate for architectural drawings —
    saving this page marks every architectural ProjectDrawing on the project
    reviewed, which generate_beme() requires before it will run."""

    def _extraction_notices(self, project):
        drawings = project.drawings.filter(discipline='architectural')
        excluded_candidates = []
        external_works_noted = []
        for drawing in drawings:
            excluded_candidates += drawing.extraction_flags.get('excluded_candidates', [])
            external_works_noted += drawing.extraction_flags.get('external_works_noted', [])
        return excluded_candidates, external_works_noted

    def _area_mismatch_pct(self, project):
        if not (project.footprint_width_m and project.footprint_length_m):
            return None
        footprint_area = project.footprint_width_m * project.footprint_length_m
        if footprint_area <= 0:
            return None
        total_room_area = sum((room.area for room in project.rooms.all()), Decimal('0'))
        return abs(total_room_area - footprint_area) / footprint_area * 100

    def _context(self, project, formset, footprint_form):
        excluded_candidates, external_works_noted = self._extraction_notices(project)
        return {
            'project': project, 'formset': formset, 'footprint_form': footprint_form,
            'excluded_candidates': excluded_candidates,
            'external_works_noted': external_works_noted,
            'area_mismatch_pct': self._area_mismatch_pct(project),
            'area_mismatch_warning_pct': AREA_MISMATCH_WARNING_PCT,
        }

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        formset = RoomFormSet(queryset=Room.objects.filter(project=project), prefix='rooms')
        footprint_form = ProjectFootprintForm(instance=project)
        return render(request, 'projects/room_review.html', self._context(project, formset, footprint_form))

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        formset = RoomFormSet(request.POST, queryset=Room.objects.filter(project=project), prefix='rooms')
        footprint_form = ProjectFootprintForm(request.POST, instance=project)

        if formset.is_valid() and footprint_form.is_valid():
            # formset.save(commit=False) only returns new or actually-changed
            # rows (Django skips untouched existing forms) — so every instance
            # here was genuinely touched by the user, whether newly added or
            # an edit to a previously AI-extracted room. Either way its
            # dimensions are now human input, not an AI guess.
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            for instance in instances:
                instance.project = project
                instance.is_manual = True
                instance.confidence = 'manual'
                instance.save()
            footprint_form.save()
            ProjectDrawing.objects.filter(project=project, discipline='architectural').update(
                reviewed=True, reviewed_at=timezone.now(),
            )
            messages.success(request, 'Rooms updated and confirmed.')
            return redirect('projects:detail', pk=project.pk)

        return render(request, 'projects/room_review.html', self._context(project, formset, footprint_form))


class ProjectSpecView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        form = ProjectSpecForm(instance=getattr(project, 'spec', None))
        reinforcement_formset = ReinforcementSpecFormSet(
            instance=project, prefix='reinforcement', form_kwargs={'project': project},
        )
        member_formset = StructuralMemberFormSet(instance=project, prefix='members')
        return render(request, 'projects/spec_wizard.html', {
            'project': project,
            'form': form,
            'reinforcement_formset': reinforcement_formset,
            'member_formset': member_formset,
        })

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        form = ProjectSpecForm(request.POST, instance=getattr(project, 'spec', None))
        member_formset = StructuralMemberFormSet(request.POST, instance=project, prefix='members')
        reinforcement_formset = ReinforcementSpecFormSet(
            request.POST, instance=project, prefix='reinforcement', form_kwargs={'project': project},
        )

        if form.is_valid() and member_formset.is_valid():
            with transaction.atomic():
                spec = form.save(commit=False)
                spec.project = project
                spec.save()
                member_formset.save()

                # The Label dropdown lets a Reinforcement row point at a
                # member added in this very submission, before it has a real
                # pk — the option's value is "new:<member form index>" rather
                # than a pk. Swap those tokens for the pk member_formset.save()
                # (above) just assigned, before the reinforcement formset ever
                # sees the data.
                member_pk_by_index = {
                    str(index): member_form.instance.pk
                    for index, member_form in enumerate(member_formset.forms)
                    if member_form.instance.pk
                }
                post_data = request.POST.copy()
                for key in list(post_data.keys()):
                    if key.endswith('-structural_member') and post_data[key].startswith('new:'):
                        resolved_pk = member_pk_by_index.get(post_data[key][len('new:'):])
                        if resolved_pk:
                            post_data[key] = str(resolved_pk)

                # Re-bind after member_formset.save() (above), not before: if
                # this submission deletes a structural member that an existing
                # reinforcement row still points to, that delete cascades
                # immediately, and validating against a queryset built before
                # the deletion would let the now-dangling reference through.
                reinforcement_formset = ReinforcementSpecFormSet(
                    post_data, instance=project, prefix='reinforcement', form_kwargs={'project': project},
                )
                if reinforcement_formset.is_valid():
                    reinforcement_formset.save()
                    messages.success(request, 'Project specifications saved.')
                    return redirect('projects:detail', pk=project.pk)

                transaction.set_rollback(True)

        messages.error(request, 'Please fix the errors below.')
        return render(request, 'projects/spec_wizard.html', {
            'project': project,
            'form': form,
            'reinforcement_formset': reinforcement_formset,
            'member_formset': member_formset,
        })
