from core.ai_provider import AIProviderError, ask_struxy

HISTORY_LIMIT = 10  # exchanges (user+assistant pairs), not raw messages


class ChatError(Exception):
    pass


def get_struxy_reply(message, history):
    """history is a list of StruxyMessage ordered oldest-first, already capped to
    the last HISTORY_LIMIT exchanges by the caller."""
    conversation_history = [{'role': m.role, 'content': m.content} for m in history]
    try:
        return ask_struxy(message, conversation_history)
    except AIProviderError as exc:
        raise ChatError(str(exc)) from exc
