from django.urls import path

from . import views

app_name = 'beme'

urlpatterns = [
    path('prices/', views.PriceListView.as_view(), name='price_list'),
    path('projects/<int:pk>/boq/generate/', views.BEMEGenerateView.as_view(), name='generate'),
    path('projects/<int:pk>/boq/letterhead/', views.BEMELetterheadView.as_view(), name='letterhead'),
    path('projects/<int:pk>/boq/edit/', views.BEMEEditView.as_view(), name='edit'),
    path('projects/<int:pk>/boq/export/', views.BEMEExportView.as_view(), name='export'),
    path('projects/<int:pk>/boq/delete/', views.BEMEDeleteView.as_view(), name='delete'),
    path('projects/<int:pk>/boq/', views.BEMEDetailView.as_view(), name='detail'),
]
