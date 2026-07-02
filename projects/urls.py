from django.urls import path

from . import views

app_name = 'projects'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('projects/new/', views.ProjectCreateView.as_view(), name='create'),
    path('projects/<int:pk>/', views.ProjectDetailView.as_view(), name='detail'),
    path('projects/<int:pk>/delete/', views.ProjectDeleteView.as_view(), name='delete'),
    path('projects/<int:pk>/drawings/upload/', views.ProjectDrawingUploadView.as_view(), name='drawing_upload'),
    path('projects/<int:pk>/rooms/', views.RoomReviewView.as_view(), name='room_review'),
    path('projects/<int:pk>/spec/', views.ProjectSpecView.as_view(), name='spec'),
]
