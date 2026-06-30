from django.contrib import admin

from .models import BEMEDocument, BEMEElement, BEMELineItem, MaterialPrice


@admin.register(MaterialPrice)
class MaterialPriceAdmin(admin.ModelAdmin):
    list_display = ['material_name', 'city', 'unit', 'rate', 'previous_rate', 'date_updated']
    list_filter = ['city']
    search_fields = ['material_name']
    list_editable = ['unit', 'rate', 'previous_rate']
    ordering = ['material_name', 'city']


class BEMELineItemInline(admin.TabularInline):
    model = BEMELineItem
    extra = 0


@admin.register(BEMEElement)
class BEMEElementAdmin(admin.ModelAdmin):
    list_display = ['project', 'element_number', 'title', 'total']
    list_filter = ['title']
    inlines = [BEMELineItemInline]


@admin.register(BEMEDocument)
class BEMEDocumentAdmin(admin.ModelAdmin):
    list_display = ['project', 'grand_total', 'preliminaries', 'contract_sum', 'generated_at']
