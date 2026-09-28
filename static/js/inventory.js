const I18N = JSON.parse(document.getElementById('page-translations').textContent);
const tbody = document.getElementById("parts-table-body");
const resetButton = document.getElementById("resetSearchButton");

function renderTable(parts) {
  tbody.innerHTML = "";
  if (!parts || parts.length === 0) {
    const emptyRow = document.createElement("tr");
    emptyRow.innerHTML = `<td colspan="7" class="text-center text-muted py-4">${I18N.empty_hint}</td>`;
    tbody.appendChild(emptyRow);
    return;
  }

  parts.forEach(part => {
    let projectBadges = '';
    if (part.projects && part.projects.length > 0) {
      projectBadges = part.projects.map(p => `<a href="/project_details?project_id=${p.id}" class="badge bg-secondary text-decoration-none me-1">${p.name}</a>`).join('');
    } else {
      projectBadges = `<span class="badge bg-light text-muted border">${I18N.badge_loose_part}</span>`;
    }

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
      <td>${projectBadges}</td>
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

// Load templates and project checkboxes on page load
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

  // Load CSV Templates
  fetch("/api/inventory/get_available_file_templates")
    .then(response => response.json())
    .then(templates => {
      const select = document.getElementById("templateSelect");
      if (!select) return;
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

  // Load Projects for Add Part Modal
  fetch("/api/projects/")
    .then(response => response.json())
    .then(projects => {
      const container = document.getElementById("project-checkboxes-container");
      if (!container) return;
      if (!projects || projects.length === 0) {
        container.innerHTML = `<small class="text-muted">${I18N.select_projects_help}</small>`;
        return;
      }
      container.innerHTML = projects.map(p => `
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="project_ids" value="${p.id}" id="proj_${p.id}">
          <label class="form-check-label" for="proj_${p.id}">${p.name}</label>
        </div>
      `).join('');
    })
    .catch(error => {
      console.error("Error fetching projects for modal:", error);
    });
});
