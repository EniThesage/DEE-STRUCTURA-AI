document.addEventListener('DOMContentLoaded', function () {
  const table = document.getElementById('room-table');
  const tbody = table.querySelector('tbody');
  const totalForms = document.querySelector('[name="rooms-TOTAL_FORMS"]');
  const addBtn = document.getElementById('add-room-btn');
  const template = document.getElementById('empty-room-template');

  function recalcArea(row) {
    const widthInput = row.querySelector('[name$="-width"]');
    const lengthInput = row.querySelector('[name$="-length"]');
    const width = parseFloat(widthInput.value) || 0;
    const length = parseFloat(lengthInput.value) || 0;
    row.querySelector('.room-area').textContent = (width * length).toFixed(2);
  }

  function wireRow(row) {
    recalcArea(row);

    row.querySelectorAll('[name$="-width"], [name$="-length"]').forEach(function (input) {
      input.addEventListener('input', function () {
        recalcArea(row);
      });
    });

    const deleteCheckbox = row.querySelector('[name$="-DELETE"]');
    const removeBtn = row.querySelector('.remove-room-btn');
    deleteCheckbox.style.display = 'none';

    removeBtn.addEventListener('click', function () {
      deleteCheckbox.checked = !deleteCheckbox.checked;
      row.classList.toggle('room-row-removed', deleteCheckbox.checked);
      removeBtn.textContent = deleteCheckbox.checked ? 'Undo' : 'Remove';
    });
  }

  tbody.querySelectorAll('.room-row').forEach(wireRow);

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
