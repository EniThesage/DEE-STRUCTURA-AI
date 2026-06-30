from datetime import date
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from projects.models import Project

from .excel import build_beme_workbook
from .forms import BEMELetterheadForm, BEMELineItemFormSet
from .models import BEMEElement, BEMELineItem, MaterialPrice
from .services import BEMEGenerationError, generate_beme, paginate_element, recompute_document_totals, relabel_element


def _bill_description(project):
    return (
        f'Bill of Quantities for the proposed construction of '
        f'{project.get_building_type_display().lower()} building at {project.get_location_display()} '
        f'for {project.client_name}'
    )


def _beme_context(project):
    """Returns (document, elements_data, bill_description), or None if no BOQ has been generated."""
    document = getattr(project, 'beme_document', None)
    if document is None:
        return None

    elements = project.beme_elements.prefetch_related('line_items')
    elements_data = [{'element': element, 'pages': paginate_element(element)} for element in elements]
    return document, elements_data, _bill_description(project)


class PriceListView(LoginRequiredMixin, TemplateView):
    template_name = 'boq/price_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cities = Project.CITY_CHOICES
        selected_city = self.request.GET.get('city', cities[0][0])
        if selected_city not in dict(cities):
            selected_city = cities[0][0]

        context['cities'] = cities
        context['selected_city'] = selected_city
        context['prices'] = MaterialPrice.objects.filter(city=selected_city)
        return context


class BEMEGenerateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        try:
            generate_beme(project)
        except BEMEGenerationError as exc:
            messages.error(request, str(exc))
            return redirect('projects:detail', pk=project.pk)

        messages.success(request, 'BOQ generated.')
        return redirect('beme:detail', pk=project.pk)


class BEMEDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        context = _beme_context(project)
        if context is None:
            messages.info(request, 'No BOQ has been generated for this project yet.')
            return redirect('projects:detail', pk=project.pk)

        document, elements_data, bill_description = context
        return render(request, 'boq/detail.html', {
            'project': project,
            'document': document,
            'elements_data': elements_data,
            'bill_description': bill_description,
        })


class BEMEEditView(LoginRequiredMixin, View):
    def _build_entries(self, project, data=None):
        elements = project.beme_elements.prefetch_related('line_items')
        return [
            {
                'element': element,
                'formset': BEMELineItemFormSet(
                    data, queryset=element.line_items.all(), prefix=f'el{element.pk}',
                ),
            }
            for element in elements
        ]

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        document = getattr(project, 'beme_document', None)
        if document is None:
            messages.info(request, 'Generate a BOQ for this project before editing line items.')
            return redirect('projects:detail', pk=project.pk)

        entries = self._build_entries(project)
        return render(request, 'boq/edit.html', {'project': project, 'document': document, 'entries': entries})

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        document = getattr(project, 'beme_document', None)
        if document is None:
            messages.info(request, 'Generate a BOQ for this project before editing line items.')
            return redirect('projects:detail', pk=project.pk)

        entries = self._build_entries(project, data=request.POST)

        if all(entry['formset'].is_valid() for entry in entries):
            with transaction.atomic():
                for entry in entries:
                    element = entry['element']
                    formset = entry['formset']
                    # Query BEMELineItem directly, not element.line_items —
                    # `element` came from a prefetch_related('line_items')
                    # queryset built in _build_entries, whose cached .all()
                    # would otherwise ignore rows saved later in this request.
                    next_sort = (BEMELineItem.objects.filter(element=element)
                                 .aggregate(Max('sort_order'))['sort_order__max'] or 0) + 1

                    instances = formset.save(commit=False)
                    for obj in formset.deleted_objects:
                        obj.delete()
                    for obj in instances:
                        obj.element = element
                        if obj.pk is None:
                            obj.sort_order = next_sort
                            next_sort += 1
                        if obj.is_section_header:
                            obj.qty = obj.rate = obj.amount = None
                        elif obj.is_provisional_sum:
                            obj.qty = obj.rate = None
                        obj.save()

                    if BEMELineItem.objects.filter(element=element).exists():
                        relabel_element(element)
                    else:
                        element.delete()

                recompute_document_totals(document)

            messages.success(request, 'BOQ line items updated.')
            return redirect('beme:detail', pk=project.pk)

        messages.error(request, 'Please fix the errors below.')
        return render(request, 'boq/edit.html', {'project': project, 'document': document, 'entries': entries})


class BEMEExportView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        context = _beme_context(project)
        if context is None:
            messages.info(request, 'No BOQ has been generated for this project yet.')
            return redirect('projects:detail', pk=project.pk)

        document, elements_data, bill_description = context
        workbook = build_beme_workbook(project, document, elements_data, bill_description)

        safe_name = ''.join(c for c in project.name if c.isalnum() or c in ' _-').strip().replace(' ', '_')
        filename = f'{safe_name}_BOQ_{date.today():%Y-%m-%d}.xlsx'

        buffer = BytesIO()
        workbook.save(buffer)

        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class BEMEDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        document = getattr(project, 'beme_document', None)
        if document is None:
            messages.info(request, 'No BOQ exists for this project.')
            return redirect('projects:detail', pk=project.pk)

        BEMEElement.objects.filter(project=project).delete()
        document.delete()
        messages.success(request, 'BOQ deleted.')
        return redirect('projects:detail', pk=project.pk)


class BEMELetterheadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        document = getattr(project, 'beme_document', None)
        if document is None:
            messages.info(request, 'Generate a BOQ for this project before setting up a letterhead.')
            return redirect('projects:detail', pk=project.pk)

        form = BEMELetterheadForm(instance=document)
        return render(request, 'boq/letterhead_form.html', {'project': project, 'form': form})

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        document = getattr(project, 'beme_document', None)
        if document is None:
            messages.info(request, 'Generate a BOQ for this project before setting up a letterhead.')
            return redirect('projects:detail', pk=project.pk)

        form = BEMELetterheadForm(request.POST, instance=document)
        if form.is_valid():
            form.save()
            messages.success(request, 'Letterhead saved.')
            return redirect('beme:detail', pk=project.pk)

        messages.error(request, 'Please fix the errors below.')
        return render(request, 'boq/letterhead_form.html', {'project': project, 'form': form})
