document.addEventListener('DOMContentLoaded', function () {
  const overlay = document.getElementById('confirm-modal');
  if (!overlay) return;

  const titleEl = document.getElementById('confirm-modal-title');
  const bodyEl = document.getElementById('confirm-modal-body');
  const confirmBtn = document.getElementById('confirm-modal-confirm');
  const cancelBtn = document.getElementById('confirm-modal-cancel');
  let pendingForm = null;

  function closeModal() {
    overlay.classList.remove('is-open');
    pendingForm = null;
  }

  document.addEventListener('submit', function (e) {
    const form = e.target;
    if (!form.classList || !form.classList.contains('confirm-delete-form')) return;
    if (form.dataset.confirmed === 'true') return;

    e.preventDefault();
    titleEl.textContent = form.dataset.confirmTitle || 'Are you sure?';
    bodyEl.textContent = form.dataset.confirmBody || 'This action cannot be undone.';
    pendingForm = form;
    overlay.classList.add('is-open');
  });

  confirmBtn.addEventListener('click', function () {
    if (!pendingForm) return;
    pendingForm.dataset.confirmed = 'true';
    pendingForm.requestSubmit();
    closeModal();
  });

  cancelBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeModal();
  });
});
