from django.urls import path

from . import views

app_name = 'struxy'

urlpatterns = [
    path('messages/', views.StruxyHistoryView.as_view(), name='history'),
    path('messages/send/', views.StruxyMessageView.as_view(), name='send'),
]
