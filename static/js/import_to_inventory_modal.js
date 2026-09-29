let _importProjectsLoaded = false;
let _cachedImportProjects = [];
const _importTranslations = (() => {
  const el = document.getElementById('page-translations');
  return el ? JSON.parse(el.textContent || '{}') : {};
})();

async function loadImportProjects() {
  if (_importProjectsLoaded) return _cachedImportProjects;
  try {
    const res = await fetch('/api/projects/');
    if (res.ok) {
      _cachedImportProjects = await res.json();
      _importProjectsLoaded = true;
    }
  } catch (e) {
    console.error('Failed to load projects', e);
  }
  return _cachedImportProjects;
}

window.openImportModal = async function(source, extId, name, metaText, defaultQty = 10) {
  const sourceEl = document.getElementById('importSource');
  const extIdEl = document.getElementById('importExtId');
  const nameEl = document.getElementById('importPartName');
  const metaEl = document.getElementById('importPartMeta');
  const badgeEl = document.getElementById('importSourceBadge');
  const qtyEl = document.getElementById('importQuantity');
  const locEl = document.getElementById('importLocation');
  const noteEl = document.getElementById('importNote');

  if (!sourceEl) return;

  sourceEl.value = source;
  extIdEl.value = extId;
  nameEl.textContent = name || `Part #${extId}`;
  metaEl.textContent = metaText || '';
  if (qtyEl) qtyEl.value = defaultQty;
  if (locEl) locEl.value = 'Default Storage';
  if (noteEl) noteEl.value = '';

  const s = (source || '').toLowerCase();
  if (s === 'jlcparts') {
    badgeEl.className = 'badge bg-primary';
    badgeEl.textContent = 'JLCPCB';
  } else if (s === 'altium') {
    badgeEl.className = 'badge bg-dark';
    badgeEl.textContent = 'Altium';
  } else if (s === 'kicad') {
    badgeEl.className = 'badge bg-secondary';
    badgeEl.textContent = 'KiCad';
  } else if (s === 'fasteners') {
    badgeEl.className = 'badge bg-secondary';
    badgeEl.textContent = _importTranslations.tab_fasteners || 'Fasteners';
  } else {
    badgeEl.className = 'badge bg-secondary';
    badgeEl.textContent = source;
  }

  // Load projects checkboxes
  const projContainer = document.getElementById('importProjectCheckboxes');
  if (projContainer) {
    projContainer.innerHTML = '<small class="text-muted">Loading projects...</small>';
    const projects = await loadImportProjects();
    if (projects.length === 0) {
      projContainer.innerHTML = '<small class="text-muted">No projects found</small>';
    } else {
      projContainer.innerHTML = projects.map(p => `
        <div class="form-check">
          <input class="form-check-input import-proj-cb" type="checkbox" value="${p.id}" id="import_proj_${p.id}">
          <label class="form-check-label text-truncate" for="import_proj_${p.id}">
            ${escapeHtmlModal(p.name)}
          </label>
        </div>
      `).join('');
    }
  }

  const modalEl = document.getElementById('importToInventoryModal');
  if (modalEl) {
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  }
};

function escapeHtmlModal(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[m]);
}

document.addEventListener('DOMContentLoaded', () => {
  const confirmBtn = document.getElementById('confirmImportBtn');
  if (!confirmBtn) return;

  confirmBtn.addEventListener('click', async function() {
    const btn = this;
    const source = document.getElementById('importSource').value;
    const extId = document.getElementById('importExtId').value;
    const location = document.getElementById('importLocation').value.trim() || 'Default Storage';
    const qty = parseInt(document.getElementById('importQuantity').value, 10);
    const note = document.getElementById('importNote').value.trim();

    const selectedProjects = [];
    document.querySelectorAll('.import-proj-cb:checked').forEach(cb => {
      selectedProjects.push(parseInt(cb.value, 10));
    });

    if (isNaN(qty) || qty < 0) {
      alert('Please enter a valid quantity');
      return;
    }

    btn.disabled = true;
    try {
      const res = await fetch('/api/inventory/add_part_to_inventory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_source: source,
          external_part_id: String(extId),
          quantity: qty,
          storage_location: location,
          note: note,
          project_ids: selectedProjects
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to add component to inventory');
      }

      const result = await res.json();

      const modalEl = document.getElementById('importToInventoryModal');
      const modal = bootstrap.Modal.getInstance(modalEl);
      if (modal) modal.hide();

      if (window.confirm('Component successfully added to inventory! Would you like to view its details?')) {
        window.location.href = `/component_details?part_id=${result.id}`;
      }
    } catch (err) {
      alert(err.message || 'Error adding to inventory');
    } finally {
      btn.disabled = false;
    }
  });
});
