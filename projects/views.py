from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView

from beme.models import BEMEDocument

from .forms import (
    FloorPlanUploadForm, ProjectFootprintForm, ProjectForm, ProjectSpecForm, ReinforcementSpecFormSet,
    StructuralMemberFormSet,
)
from .models import Project, Room
from .services import ExtractionError, extract_rooms_from_floor_plan

RoomFormSet = modelformset_factory(
    Room,
    fields=['name', 'width', 'length'],
    extra=1,
    can_delete=True,
)


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
        context['upload_form'] = FloorPlanUploadForm()
        context['floor_plans'] = self.object.floor_plans.all()
        context['rooms'] = self.object.rooms.all()
        context['spec'] = getattr(self.object, 'spec', None)
        return context


class FloorPlanUploadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        form = FloorPlanUploadForm(request.POST, request.FILES)

        if not form.is_valid():
            messages.error(request, 'Please upload a valid PDF, JPG, PNG, or WEBP file.')
            return redirect('projects:detail', pk=project.pk)

        floor_plan = form.save(commit=False)
        floor_plan.project = project
        floor_plan.extraction_status = 'processing'
        floor_plan.save()

        try:
            data = extract_rooms_from_floor_plan(floor_plan.file.path)
        except ExtractionError as exc:
            floor_plan.extraction_status = 'failed'
            floor_plan.extraction_error = str(exc)
            floor_plan.save()
            messages.warning(request, str(exc))
            return redirect('projects:detail', pk=project.pk)

        footprint_width = _safe_decimal(data.get('building_width_m'))
        footprint_length = _safe_decimal(data.get('building_length_m'))
        if footprint_width and footprint_length:
            project.footprint_width_m = footprint_width
            project.footprint_length_m = footprint_length
            project.save(update_fields=['footprint_width_m', 'footprint_length_m'])

        rooms = data.get('rooms', [])
        flagged_count = 0
        for room in rooms:
            width = room.get('width_m') or 0
            length = room.get('length_m') or 0
            name = room.get('name') or 'Room'
            confidence = room.get('confidence') or 'medium'

            # A room with both dimensions under ~1.2m almost certainly isn't a
            # room at all — it's a structural column/post/pier the vision model
            # mistook for an enclosed space. Don't silently accept it as floor
            # area; flag it for manual review instead.
            if width and length and width < 1.2 and length < 1.2:
                name = f'{name} (check: looks like a column/post, not a room)'
                confidence = 'low'
                flagged_count += 1

            Room.objects.create(
                project=project,
                name=name,
                width=width,
                length=length,
                confidence=confidence,
                is_manual=False,
            )

        floor_plan.extraction_status = 'completed'
        floor_plan.save()

        notice = f'Extracted {len(rooms)} rooms from the floor plan.'
        if flagged_count:
            notice += f' {flagged_count} flagged as possible structural elements — please review before generating a BOQ.'
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
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        formset = RoomFormSet(queryset=Room.objects.filter(project=project), prefix='rooms')
        footprint_form = ProjectFootprintForm(instance=project)
        return render(request, 'projects/room_review.html', {
            'project': project, 'formset': formset, 'footprint_form': footprint_form,
        })

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
            messages.success(request, 'Rooms updated.')
            return redirect('projects:detail', pk=project.pk)

        return render(request, 'projects/room_review.html', {
            'project': project, 'formset': formset, 'footprint_form': footprint_form,
        })


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
