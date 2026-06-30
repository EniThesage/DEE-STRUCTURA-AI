from django.contrib import admin

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'title', 'company_name', 'email', 'phone_number', 'created_at']
    list_filter = ['title', 'created_at']
    search_fields = ['name', 'email', 'company_name', 'phone_number', 'message']
    readonly_fields = ['created_at', 'submitted_by']
    ordering = ['-created_at']
