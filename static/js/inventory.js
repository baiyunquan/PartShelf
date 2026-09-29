const I18N = JSON.parse(document.getElementById('page-translations').textContent || '{}');
const tbody = document.getElementById("parts-table-body");
const resetButton = document.getElementById("resetSearchButton");
const warehouseStatusFilter = document.getElementById("warehouseStatusFilter");

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[m]);
}

function getSourceBadge(source) {
  const s = (source || '').toLowerCase();
  if (s === 'jlcparts') {
    return '<span class="badge bg-primary">JLCPCB</span>';
  } else if (s === 'altium') {
    return '<span class="badge bg-dark">Altium</span>';
  } else if (s === 'kicad') {
    return '<span class="badge bg-secondary">KiCad</span>';
  } else if (s === 'fasteners') {
    return `<span class="badge bg-secondary">${escapeHtml(I18N.source_fasteners || 'Mechanical')}</span>`;
  }
  return `<span class="badge bg-light text-dark border">${escapeHtml(source || '-')}</span>`;
}

function renderTable(parts) {
  tbody.innerHTML = "";
  if (!parts || parts.length === 0) {
    const emptyRow = document.createElement("tr");
    emptyRow.innerHTML = `<td colspan="9" class="text-center text-muted py-4">${I18N.empty_hint || 'No inventory parts found.'}</td>`;
    tbody.appendChild(emptyRow);
    return;
  }

  parts.forEach(part => {
    let projectBadges = '';
    if (part.projects && part.projects.length > 0) {
      projectBadges = part.projects.map(p => `<a href="/project_details?project_id=${p.id}" class="badge bg-secondary text-decoration-none me-1">${escapeHtml(p.name)}</a>`).join('');
    } else {
      projectBadges = `<span class="badge bg-light text-muted border">${I18N.badge_loose_part || 'Loose Part'}</span>`;
    }

    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="badge bg-light text-dark border">#${part.id}</span></td>
      <td>
        <a href="/component_details?part_id=${part.id}" class="fw-bold text-decoration-none text-primary">
          ${escapeHtml(part.name || '-')}
        </a>
        ${part.note ? `<small class="d-block text-muted text-truncate" style="max-width: 250px;">${escapeHtml(part.note)}</small>` : ''}
      </td>
      <td>${getSourceBadge(part.library_source)}</td>
      <td>
        <div><code>${escapeHtml(part.package || '-')}</code></div>
        <small class="text-muted">${escapeHtml(part.manufacturer || '-')}</small>
      </td>
      <td>
        <span class="badge bg-light text-dark border">${escapeHtml(part.storage_location || 'Default Storage')}</span>
      </td>
      <td>
        <span class="badge ${part.warehouse_status === 'in_warehouse' ? 'bg-success' : 'bg-secondary'}">
          ${part.warehouse_status === 'in_warehouse' ? (I18N.warehouse_filter_in || 'In warehouse') : (I18N.warehouse_filter_out || 'Not added to warehouse')}
        </span>
        ${part.warehouse_box_id ? `<small class="d-block text-muted">${escapeHtml(I18N.warehouse_box || 'Box')} ${escapeHtml(part.warehouse_box_id)} / ${escapeHtml(I18N.warehouse_drawer || 'Drawer')} ${escapeHtml(part.warehouse_drawer_code || '')}</small>` : ''}
      </td>
      <td>
        <span class="badge ${part.quantity > 0 ? 'bg-success' : 'bg-danger'}">
          ${part.quantity !== null && part.quantity !== undefined ? part.quantity : 0}
        </span>
      </td>
      <td>${projectBadges}</td>
      <td class="text-end">
        <a href="/component_details?part_id=${part.id}" class="btn btn-outline-primary btn-sm text-nowrap">
          ${I18N.btn_details || 'Details'}
        </a>
      </td>
    `;
    tbody.appendChild(row);
  });
}

function loadAllParts() {
  document.getElementById('searchInput').value = '';
  resetButton.style.display = 'none';

  const statusQuery = warehouseStatusFilter.value ? `?warehouse_status=${encodeURIComponent(warehouseStatusFilter.value)}` : '';
  fetch(`/api/inventory/get_parts_inventory${statusQuery}`)
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
  const statusQuery = warehouseStatusFilter.value ? `&warehouse_status=${encodeURIComponent(warehouseStatusFilter.value)}` : '';
  fetch(`/api/inventory/search?search_key=${encodeURIComponent(searchKey)}${statusQuery}`)
    .then(res => res.json())
    .then(parts => renderTable(parts))
    .catch(err => {
      console.error(I18N.alert_fetch_error, err);
      alert(I18N.alert_fetch_error || 'Error searching inventory');
    });
}

// Search button click
document.getElementById('searchButton').addEventListener('click', function() {
  handleSearch(document.getElementById('searchInput').value);
});
resetButton.addEventListener('click', loadAllParts);
warehouseStatusFilter.addEventListener('change', () => {
  const query = document.getElementById('searchInput').value.trim();
  if (query) handleSearch(query);
  else loadAllParts();
});

// Enter key on search input
document.getElementById('searchInput').addEventListener('keyup', function(e) {
  if (e.key === 'Enter') {
    handleSearch(this.value);
  }
});

// ==========================================
// External Library Search inside Add Modal
// ==========================================

const externalSearchInput = document.getElementById('externalSearchInput');
const btnExternalSearch = document.getElementById('btnExternalSearch');
const externalTargetSelect = document.getElementById('externalTargetSelect');
const externalSearchResults = document.getElementById('externalSearchResults');
const selectedPartPreview = document.getElementById('selectedPartPreview');
const savePartBtn = document.getElementById('savePartBtn');
const fastenerVariantSelection = document.getElementById('fastenerVariantSelection');
const fastenerNominalSelect = document.getElementById('fastenerNominalSelect');
const fastenerLengthSelect = document.getElementById('fastenerLengthSelect');
const fastenerLengthGroup = document.getElementById('fastenerLengthGroup');
const confirmFastenerVariantButton = document.getElementById('confirmFastenerVariant');
let pendingFastenerStandard = null;

async function executeExternalSearch() {
  const query = (externalSearchInput.value || '').trim();
  if (!query) return;

  const target = externalTargetSelect.value || 'all';
  externalSearchResults.style.display = 'block';
  externalSearchResults.innerHTML = `<div class="text-center text-muted py-3">${I18N.searching_libraries || 'Searching external libraries...'}</div>`;

  try {
    const limit = target === 'fasteners' ? 100 : 15;
    const res = await fetch(`/api/libraries/search?q=${encodeURIComponent(query)}&target=${encodeURIComponent(target)}&limit=${limit}`);
    const data = await res.json();
    renderExternalSearchResults(data, target);
  } catch (e) {
    externalSearchResults.innerHTML = `<div class="text-danger py-2">Search error. Please retry.</div>`;
  }
}

function renderExternalSearchResults(data, target) {
  externalSearchResults.innerHTML = '';
  let items = [];

  if (target === 'all') {
    (data.jlcparts || []).forEach(item => items.push({ ...item, _source: 'jlcparts' }));
    (data.altium || []).forEach(item => items.push({ ...item, _source: 'altium' }));
    (data.kicad || []).forEach(item => items.push({ ...item, _source: 'kicad' }));
    (data.fasteners?.items || []).forEach(item => items.push({ ...item, _source: 'fasteners' }));
  } else if (target === 'jlcparts') {
    items = (data.jlcparts || []).map(item => ({ ...item, _source: 'jlcparts' }));
  } else if (target === 'altium') {
    items = (data.altium || []).map(item => ({ ...item, _source: 'altium' }));
  } else if (target === 'kicad') {
    items = (data.kicad || []).map(item => ({ ...item, _source: 'kicad' }));
  } else if (target === 'fasteners') {
    items = (data.fasteners?.items || []).map(item => ({ ...item, _source: 'fasteners' }));
  }

  if (items.length === 0) {
    externalSearchResults.innerHTML = `<div class="text-muted text-center py-3">${I18N.no_external_results || 'No matching components found.'}</div>`;
    return;
  }

  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'd-flex justify-content-between align-items-center p-2 border-bottom hover-bg';
    
    let title = '';
    let meta = '';
    let extId = '';
    let badge = '';

    if (item._source === 'jlcparts') {
      title = item.mfr || `C${item.lcsc}`;
      meta = `Package: ${item.package || '-'} | Mfr: ${item.manufacturer || '-'} | Stock: ${(item.stock || 0).toLocaleString()}`;
      extId = String(item.lcsc);
      badge = '<span class="badge bg-primary">JLCPCB</span>';
    } else if (item._source === 'altium') {
      title = item.lib_reference || item.mfr_part_number;
      meta = `Package: ${item.package || '-'} | Mfr: ${item.manufacturer || '-'} | Cat: ${item.category || '-'}`;
      extId = String(item.id);
      badge = '<span class="badge bg-dark">Altium</span>';
    } else if (item._source === 'kicad') {
      title = item.name || item.value;
      meta = `Library: ${item.library || '-'} | Footprint: ${item.footprint || '-'}`;
      extId = String(item.id);
      badge = '<span class="badge bg-secondary">KiCad</span>';
    } else if (item._source === 'fasteners') {
      title = item.standard_code || item.standard_name || '';
      meta = `${item.authority || '-'} | ${item.category_group_zh || item.category_group || '-'} | ${item.description || ''}`;
      extId = String(item.standard_code || '');
      badge = `<span class="badge bg-secondary">${escapeHtml(I18N.source_fasteners || 'Mechanical')}</span>`;
    }

    div.innerHTML = `
      <div class="me-2 text-truncate">
        <div class="d-flex align-items-center gap-1">
          ${badge}
          <strong class="text-dark">${escapeHtml(title)}</strong>
        </div>
        <small class="text-secondary d-block text-truncate">${escapeHtml(meta)}</small>
      </div>
      <button type="button" class="btn btn-outline-primary btn-sm text-nowrap select-item-btn">
        ${I18N.btn_select || 'Select'}
      </button>
    `;

    div.querySelector('.select-item-btn').addEventListener('click', () => {
      if (item._source === 'fasteners') {
        loadFastenerVariantOptions(item, title, meta);
      } else {
        selectExternalPart(item._source, extId, title, meta);
      }
    });

    externalSearchResults.appendChild(div);
  });
}

function selectExternalPart(source, extId, title, meta) {
  pendingFastenerStandard = null;
  if (fastenerVariantSelection) fastenerVariantSelection.style.display = 'none';
  document.getElementById('selectedSource').value = source;
  document.getElementById('selectedExtId').value = extId;

  document.getElementById('previewPartName').textContent = title;
  document.getElementById('previewPartMeta').textContent = meta;
  document.getElementById('previewPartBadge').innerHTML = getSourceBadge(source);
  selectedPartPreview.style.display = 'block';

  savePartBtn.disabled = false;
}

async function loadFastenerVariantOptions(item, title, meta) {
  if (!fastenerVariantSelection) return;
  fastenerVariantSelection.style.display = 'block';
  fastenerVariantSelection.querySelector('.card-body').setAttribute('aria-busy', 'true');
  try {
    const response = await fetch(`/api/libraries/fasteners/${encodeURIComponent(item.standard_code)}`);
    if (!response.ok) throw new Error(I18N.fastener_load_failed || 'Unable to load standard dimensions.');
    const detail = await response.json();
    pendingFastenerStandard = { item, title, meta, detail };
    fastenerNominalSelect.replaceChildren();
    (detail.param_rows || []).forEach(row => {
      const option = document.createElement('option');
      option.value = row.nominal;
      option.textContent = row.nominal;
      fastenerNominalSelect.appendChild(option);
    });
    fastenerLengthSelect.replaceChildren();
    (detail.length_rows || []).forEach(row => {
      const option = document.createElement('option');
      option.value = row.key;
      option.textContent = row.key;
      fastenerLengthSelect.appendChild(option);
    });
    const needsLength = Boolean(detail.standard?.has_length);
    fastenerLengthGroup.style.display = needsLength ? '' : 'none';
    confirmFastenerVariantButton.disabled = !fastenerNominalSelect.options.length ||
      (needsLength && !fastenerLengthSelect.options.length);
    document.getElementById('selectedSource').value = '';
    document.getElementById('selectedExtId').value = '';
    selectedPartPreview.style.display = 'none';
    savePartBtn.disabled = true;
  } catch (error) {
    pendingFastenerStandard = null;
    fastenerVariantSelection.style.display = 'none';
    alert(error.message || I18N.fastener_load_failed || 'Unable to load standard dimensions.');
  } finally {
    fastenerVariantSelection.querySelector('.card-body').removeAttribute('aria-busy');
  }
}

confirmFastenerVariantButton?.addEventListener('click', () => {
  if (!pendingFastenerStandard) return;
  const { item, title, meta, detail } = pendingFastenerStandard;
  const nominal = fastenerNominalSelect.value;
  const length = detail.standard?.has_length ? fastenerLengthSelect.value : null;
  if (!nominal || (detail.standard?.has_length && !length)) return;
  const externalId = window.buildFastenerVariantId(item.standard_code, nominal, length);
  const size = length ? `${nominal} × ${length}${String(length).toLowerCase().includes('in') ? '' : ' mm'}` : nominal;
  selectExternalPart('fasteners', externalId, `${title} ${size}`, `${meta} | ${size}`);
});

btnExternalSearch.addEventListener('click', executeExternalSearch);
externalSearchInput.addEventListener('keyup', (e) => {
  if (e.key === 'Enter') executeExternalSearch();
});

// Add Part Form Submit
document.getElementById('addPartInventoryForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const source = document.getElementById('selectedSource').value;
  const extId = document.getElementById('selectedExtId').value;
  if (!source || !extId) {
    alert(I18N.select_hint || 'Please select an external component first.');
    return;
  }

  const quantity = parseInt(document.getElementById('inputQuantity').value || '1', 10);
  const location = document.getElementById('inputLocation').value.trim();
  const note = document.getElementById('inputNote').value.trim();

  // Checkboxes
  const projectCheckboxes = document.querySelectorAll('#project-checkboxes-container input[type="checkbox"]:checked');
  const projectIds = Array.from(projectCheckboxes).map(cb => parseInt(cb.value, 10));

  const payload = {
    library_source: source,
    external_part_id: extId,
    quantity: quantity,
    storage_location: location || 'Default Storage',
    note: note || '',
    project_ids: projectIds
  };

  try {
    savePartBtn.disabled = true;
    const res = await fetch('/api/inventory/add_part_to_inventory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to add part');
    }
    
    // Close modal
    const modalEl = document.getElementById('addComponentModal');
    const modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) modal.hide();

    // Reset form
    document.getElementById('addPartInventoryForm').reset();
    document.getElementById('selectedSource').value = '';
    document.getElementById('selectedExtId').value = '';
    selectedPartPreview.style.display = 'none';
    externalSearchResults.style.display = 'none';
    externalSearchInput.value = '';
    savePartBtn.disabled = true;

    // Reload table
    loadAllParts();
  } catch (err) {
    alert(err.message || 'Error adding part to inventory');
    savePartBtn.disabled = false;
  }
});

// Load projects on page load
document.addEventListener("DOMContentLoaded", function () {
  const urlParams = new URLSearchParams(window.location.search);
  const searchParam = urlParams.get('search');
  if (searchParam) {
    document.getElementById('searchInput').value = searchParam;
    handleSearch(searchParam);
  } else {
    loadAllParts();
  }

  // Load Projects for Add Part Modal
  fetch("/api/projects/")
    .then(response => response.json())
    .then(projects => {
      const container = document.getElementById("project-checkboxes-container");
      if (!container) return;
      if (projects.length === 0) {
        container.innerHTML = `<small class="text-muted d-block">${I18N.select_projects_help || 'No projects created yet'}</small>`;
        return;
      }
      container.innerHTML = "";
      projects.filter(project => !project.is_system).forEach(project => {
        const div = document.createElement("div");
        div.className = "form-check";
        div.innerHTML = `
          <input class="form-check-input" type="checkbox" value="${project.id}" id="proj_${project.id}">
          <label class="form-check-label text-truncate" for="proj_${project.id}">
            ${escapeHtml(project.name)}
          </label>
        `;
        container.appendChild(div);
      });
    })
    .catch(error => console.error("Error loading projects:", error));
});
