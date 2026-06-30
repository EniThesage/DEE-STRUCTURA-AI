from django.contrib import admin

from .models import StruxyMessage


@admin.register(StruxyMessage)
class StruxyMessageAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'session_key', 'created_at']
    list_filter = ['role']
    search_fields = ['content', 'user__email']
