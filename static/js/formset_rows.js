function initFormsetTable(options) {
  const table = document.getElementById(options.tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const totalForms = document.querySelector('[name="' + options.prefix + '-TOTAL_FORMS"]');
  const addBtn = document.getElementById(options.addBtnId);
  const template = document.getElementById(options.templateId);
  const onRowAdded = options.onRowAdded || function () {};

  function wireRow(row) {
    const deleteCheckbox = row.querySelector('[name$="-DELETE"]');
    const removeBtn = row.querySelector('.remove-row-btn');
    if (!deleteCheckbox || !removeBtn) return;
    deleteCheckbox.style.display = 'none';

    removeBtn.addEventListener('click', function () {
      deleteCheckbox.checked = !deleteCheckbox.checked;
      row.classList.toggle('room-row-removed', deleteCheckbox.checked);
      removeBtn.textContent = deleteCheckbox.checked ? 'Undo' : 'Remove';
    });
  }

  tbody.querySelectorAll('tr').forEach(function (row) {
    wireRow(row);
    onRowAdded(row);
  });

  addBtn.addEventListener('click', function () {
    const index = parseInt(totalForms.value, 10);
    const html = template.innerHTML.replace(/__prefix__/g, index);
    const wrapper = document.createElement('tbody');
    wrapper.innerHTML = html.trim();
    const newRow = wrapper.firstElementChild;
    tbody.appendChild(newRow);
    wireRow(newRow);
    onRowAdded(newRow);
    totalForms.value = index + 1;
  });
}
