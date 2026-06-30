document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.toggle-password').forEach(function (toggle) {
    const input = document.getElementById(toggle.dataset.target);
    const icon = toggle.querySelector('i');
    if (!input) return;

    toggle.addEventListener('click', function () {
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      icon.className = showing ? 'bi bi-eye-slash' : 'bi bi-eye';
      toggle.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
    });
  });

  const password1 = document.getElementById('id_password1');
  const password2 = document.getElementById('id_password2');
  const hint = document.getElementById('password-match-hint');
  if (!password1 || !password2 || !hint) return;

  function updateHint() {
    if (!password2.value) {
      hint.textContent = '';
      hint.className = 'password-match-hint';
      return;
    }
    const matches = password1.value === password2.value;
    hint.textContent = matches ? 'Passwords match' : 'Passwords do not match';
    hint.className = 'password-match-hint ' + (matches ? 'match' : 'mismatch');
  }

  password1.addEventListener('input', updateHint);
  password2.addEventListener('input', updateHint);
});
