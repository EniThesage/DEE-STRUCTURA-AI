from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import AdminPanelView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('structura-dashboard/', AdminPanelView.as_view(), name='admin_panel'),
    path('accounts/', include('accounts.urls')),
    path('struxy/', include('struxy.urls')),
    path('', include('core.urls')),
    path('', include('beme.urls')),
    path('', include('projects.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
