(function () {
  const toggle = document.getElementById('struxy-toggle');
  const panel = document.getElementById('struxy-panel');
  const closeBtn = document.getElementById('struxy-close');
  const form = document.getElementById('struxy-form');
  const input = document.getElementById('struxy-input');
  const messagesEl = document.getElementById('struxy-messages');

  if (!toggle || !panel || !form) return;

  let historyLoaded = false;

  function getCookie(name) {
    const match = document.cookie.match('(^|;\\s*)' + name + '=([^;]*)');
    return match ? decodeURIComponent(match[2]) : null;
  }

  function appendMessage(role, content) {
    const bubble = document.createElement('div');
    bubble.className = 'struxy-bubble struxy-' + role;
    bubble.textContent = content;
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return bubble;
  }

  function loadHistory() {
    if (historyLoaded) return;
    historyLoaded = true;
    fetch('/struxy/messages/')
      .then((res) => res.json())
      .then((data) => {
        if (!data.messages || !data.messages.length) {
          appendMessage('assistant', "Hi, I'm Struxy. Ask me about concrete mixes, reinforcement, BESMM4, or how to use DEE STRUCTURA AI.");
          return;
        }
        data.messages.forEach((m) => appendMessage(m.role, m.content));
      })
      .catch(() => appendMessage('assistant', 'Could not load chat history.'));
  }

  toggle.addEventListener('click', () => {
    const isOpen = panel.classList.toggle('is-open');
    if (isOpen) {
      loadHistory();
      input.focus();
    }
  });

  closeBtn.addEventListener('click', () => {
    panel.classList.remove('is-open');
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    appendMessage('user', text);
    input.value = '';
    input.disabled = true;
    const loadingBubble = appendMessage('assistant', 'Thinking...');

    const body = new URLSearchParams({ message: text });
    fetch('/struxy/messages/send/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: body,
    })
      .then((res) => res.json())
      .then((data) => {
        loadingBubble.remove();
        if (data.error) {
          appendMessage('assistant', data.error);
        } else {
          appendMessage('assistant', data.reply);
        }
      })
      .catch(() => {
        loadingBubble.remove();
        appendMessage('assistant', 'Something went wrong reaching Struxy. Try again.');
      })
      .finally(() => {
        input.disabled = false;
        input.focus();
      });
  });
})();
