from datetime import timedelta

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, TemplateView

from beme.models import BEMEDocument
from projects.models import Project
from struxy.models import StruxyMessage

from .forms import LoginForm, SignupForm
from .models import User


class SignupView(CreateView):
    form_class = SignupForm
    template_name = 'accounts/signup.html'
    success_url = reverse_lazy('projects:dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class StructuraLoginView(LoginView):
    form_class = LoginForm
    template_name = 'accounts/login.html'


class StructuraLogoutView(LogoutView):
    pass


class AdminPanelView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/admin_panel.html'

    def get(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            raise PermissionDenied('Admin access required.')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_users'] = User.objects.count()
        context['total_projects'] = Project.objects.count()
        context['total_boqs'] = BEMEDocument.objects.count()
        context['users'] = User.objects.order_by('-date_joined')

        user_messages = StruxyMessage.objects.filter(role='user')
        context['total_struxy_messages'] = user_messages.count()
        context['struxy_messages_24h'] = user_messages.filter(
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        context['struxy_top_users'] = (
            user_messages.values('user__name', 'user__email')
            .annotate(message_count=Count('id'))
            .order_by('-message_count')[:5]
        )
        return context
