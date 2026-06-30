from django.contrib import admin

from .models import FloorPlanUpload, Project, ProjectSpec, Room


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'client_name', 'location', 'building_type', 'status', 'user', 'created_at']
    list_filter = ['location', 'building_type', 'status']
    search_fields = ['name', 'client_name']


@admin.register(FloorPlanUpload)
class FloorPlanUploadAdmin(admin.ModelAdmin):
    list_display = ['project', 'file', 'extraction_status', 'uploaded_at']
    list_filter = ['extraction_status']


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['project', 'name', 'width', 'length', 'area', 'confidence', 'is_manual']
    list_filter = ['confidence', 'is_manual']


@admin.register(ProjectSpec)
class ProjectSpecAdmin(admin.ModelAdmin):
    list_display = ['project', 'foundation_type', 'frame_type', 'roof_type', 'updated_at']
