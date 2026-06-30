from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


class StructuraUserAdmin(UserAdmin):
    ordering = ['email']
    list_display = ['email', 'name', 'role', 'is_staff', 'date_joined']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('name', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'fields': ('email', 'name', 'role', 'password1', 'password2')}),
    )
    search_fields = ['email', 'name']


admin.site.register(User, StructuraUserAdmin)
