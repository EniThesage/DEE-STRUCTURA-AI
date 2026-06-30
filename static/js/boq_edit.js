document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.boq-element-edit').forEach(function (block) {
    const tbody = block.querySelector('tbody');
    const totalForms = block.querySelector('input[name$="-TOTAL_FORMS"]');
    const addBtn = block.querySelector('.add-line-btn');
    const template = block.querySelector('.empty-line-template');

    function recalcAmount(row) {
      const qtyInput = row.querySelector('[name$="-qty"]');
      const rateInput = row.querySelector('[name$="-rate"]');
      const amountCell = row.querySelector('.line-amount');
      if (!qtyInput || !rateInput || !amountCell) return;
      const qty = parseFloat(qtyInput.value) || 0;
      const rate = parseFloat(rateInput.value) || 0;
      amountCell.textContent = Math.round(qty * rate).toLocaleString();
    }

    function wireRow(row) {
      recalcAmount(row);

      row.querySelectorAll('[name$="-qty"], [name$="-rate"]').forEach(function (input) {
        input.addEventListener('input', function () { recalcAmount(row); });
      });

      const deleteCheckbox = row.querySelector('[name$="-DELETE"]');
      const removeBtn = row.querySelector('.remove-line-btn');
      if (!deleteCheckbox || !removeBtn) return;
      deleteCheckbox.style.display = 'none';

      removeBtn.addEventListener('click', function () {
        deleteCheckbox.checked = !deleteCheckbox.checked;
        row.classList.toggle('room-row-removed', deleteCheckbox.checked);
        removeBtn.textContent = deleteCheckbox.checked ? 'Undo' : 'Remove';
      });
    }

    tbody.querySelectorAll('.line-item-row').forEach(wireRow);

    addBtn.addEventListener('click', function () {
      const index = parseInt(totalForms.value, 10);
      const html = template.innerHTML.replace(/__prefix__/g, index);
      const wrapper = document.createElement('tbody');
      wrapper.innerHTML = html.trim();
      const newRow = wrapper.firstElementChild;
      tbody.appendChild(newRow);
      wireRow(newRow);
      totalForms.value = index + 1;
    });
  });
});
