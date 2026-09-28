const I18N = JSON.parse(document.getElementById('page-translations').textContent);
const tbody = document.getElementById("parts-table-body");
const resetButton = document.getElementById("resetSearchButton");

function renderTable(parts) {
  tbody.innerHTML = "";
  if (!parts || parts.length === 0) {
    const emptyRow = document.createElement("tr");
    emptyRow.innerHTML = `<td colspan="6" class="text-center text-muted py-4">${I18N.empty_hint}</td>`;
    tbody.appendChild(emptyRow);
    return;
  }

  parts.forEach(part => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="badge bg-light text-dark border">#${part.id}</span></td>
      <td class="fw-bold">${part.name || '-'}</td>
      <td><span class="badge bg-info text-dark">${part.part_type || '-'}</span></td>
      <td><code>${part.package || '-'}</code></td>
      <td>
        <span class="badge ${part.quantity > 0 ? 'bg-success' : 'bg-danger'}">
          ${part.quantity !== null && part.quantity !== undefined ? part.quantity : 0}
        </span>
      </td>
      <td>
        <a href="/component_details?part_id=${part.id}" class="btn btn-outline-primary btn-sm">
          ${I18N.btn_details}
        </a>
      </td>
    `;
    tbody.appendChild(row);
  });
}

function loadAllParts() {
  document.getElementById('searchInput').value = '';
  if (document.getElementById('searchInputMenu')) {
    document.getElementById('searchInputMenu').value = '';
  }
  resetButton.style.display = 'none';

  fetch("/api/inventory/get_parts_inventory")
    .then(res => res.json())
    .then(parts => renderTable(parts))
    .catch(err => {
      console.error(I18N.alert_fetch_error, err);
    });
}

function handleSearch(searchKey) {
  searchKey = (searchKey || '').trim();
  if (!searchKey) {
    loadAllParts();
    return;
  }

  resetButton.style.display = 'inline-block';
  fetch(`/api/inventory/search?search_key=${encodeURIComponent(searchKey)}`)
    .then(res => res.json())
    .then(parts => renderTable(parts))
    .catch(err => {
      console.error(I18N.alert_fetch_error, err);
      alert(I18N.alert_fetch_error);
    });
}

// Search button click
document.getElementById('searchButton').addEventListener('click', function() {
  handleSearch(document.getElementById('searchInput').value);
});
resetButton.addEventListener('click', loadAllParts);

// Enter key on search input
document.getElementById('searchInput').addEventListener('keyup', function(e) {
  if (e.key === 'Enter') {
    handleSearch(this.value);
  }
});

// Load templates for CSV import
document.addEventListener("DOMContentLoaded", function () {
  // Check for URL query param search
  const urlParams = new URLSearchParams(window.location.search);
  const searchParam = urlParams.get('search');
  if (searchParam) {
    document.getElementById('searchInput').value = searchParam;
    handleSearch(searchParam);
  } else {
    loadAllParts();
  }

  fetch("/api/inventory/get_available_file_templates")
    .then(response => response.json())
    .then(templates => {
      const select = document.getElementById("templateSelect");
      templates.forEach(template => {
        const option = document.createElement("option");
        option.value = template.id;
        option.textContent = template.template_name;
        select.appendChild(option);
      });
    })
    .catch(error => {
      console.error("Error fetching templates:", error);
    });
});
