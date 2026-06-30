document.addEventListener('DOMContentLoaded', function () {
  const input = document.getElementById('material-search');
  const table = document.getElementById('price-table');
  if (!input || !table) return;

  const rows = Array.from(table.querySelectorAll('tbody tr'));

  input.addEventListener('input', function () {
    const query = input.value.trim().toLowerCase();
    rows.forEach(function (row) {
      const matches = row.dataset.materialName.includes(query);
      row.style.display = matches ? '' : 'none';
    });
  });
});
