from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from .models import StruxyMessage
from .services import ChatError, HISTORY_LIMIT, get_struxy_reply


class StruxyHistoryView(LoginRequiredMixin, View):
    def get(self, request):
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({'messages': []})

        history = StruxyMessage.objects.filter(user=request.user, session_key=session_key)
        return JsonResponse({'messages': [{'role': m.role, 'content': m.content} for m in history]})


class StruxyMessageView(LoginRequiredMixin, View):
    def post(self, request):
        text = (request.POST.get('message') or '').strip()
        if not text:
            return JsonResponse({'error': 'Message is required.'}, status=400)

        if not request.session.session_key:
            request.session.save()
        session_key = request.session.session_key

        recent = StruxyMessage.objects.filter(
            user=request.user, session_key=session_key
        ).order_by('-created_at')[:HISTORY_LIMIT * 2]
        history = list(reversed(recent))

        StruxyMessage.objects.create(user=request.user, session_key=session_key, role='user', content=text)

        try:
            reply = get_struxy_reply(text, history)
        except ChatError as exc:
            return JsonResponse({'error': str(exc)}, status=503)

        StruxyMessage.objects.create(user=request.user, session_key=session_key, role='assistant', content=reply)
        return JsonResponse({'reply': reply})
