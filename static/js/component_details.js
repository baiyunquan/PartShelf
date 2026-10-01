const I18N = JSON.parse(document.getElementById('page-translations').textContent || '{}');
const urlParams = new URLSearchParams(window.location.search);
const partId = urlParams.get("part_id");
    
if (!partId) {
  alert(I18N.missing_part_id || 'Missing part_id');
  window.location.href = "/inventory";
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[m]);
}

function renderExternalSpecs(source, extDetails, summary) {
  const container = document.getElementById("external-specs-body");
  const extBadge = document.getElementById("external-source-name");
  
  const src = (source || '').toLowerCase();
  if (src === 'jlcparts') {
    extBadge.className = 'badge bg-primary';
    extBadge.textContent = 'JLCParts Database';
  } else if (src === 'altium') {
    extBadge.className = 'badge bg-dark';
    extBadge.textContent = 'Altium JLCPCB Library';
  } else if (src === 'kicad') {
    extBadge.className = 'badge bg-secondary';
    extBadge.textContent = 'KiCad Symbol Library';
  } else if (src === 'fasteners') {
    extBadge.className = 'badge bg-secondary';
    extBadge.textContent = I18N.source_fasteners || 'Mechanical Standards';
  } else {
    extBadge.className = 'badge bg-secondary';
    extBadge.textContent = source || 'Unknown';
  }

  if (!extDetails) {
    container.innerHTML = `<div class="text-muted text-center py-4">No detailed specifications found in external library.</div>`;
    return;
  }

  if (src === 'jlcparts') {
    // JLCParts details
    const isBasic = extDetails.basic === 1 || extDetails.library_type === 'Basic';
    const isPreferred = extDetails.preferred === 1;
    let typeBadge = '<span class="badge bg-secondary">Extended</span>';
    if (isBasic) typeBadge = '<span class="badge bg-success">Basic</span>';
    else if (isPreferred) typeBadge = '<span class="badge bg-info text-dark">Preferred</span>';

    let priceRows = '';
    if (extDetails.price_breaks && extDetails.price_breaks.length > 0) {
      priceRows = extDetails.price_breaks.map(p => `
        <tr>
          <td>&ge; ${p.quantity}</td>
          <td class="fw-bold text-success">$${Number(p.price).toFixed(4)}</td>
        </tr>
      `).join('');
    }

    let attrRows = '';
    const attrs = extDetails.attributes_dict || {};
    const attrKeys = Object.keys(attrs);
    if (attrKeys.length > 0) {
      attrRows = attrKeys.map(k => `
        <tr>
          <th class="text-muted text-nowrap" style="width: 35%;">${escapeHtml(k)}</th>
          <td>${escapeHtml(attrs[k])}</td>
        </tr>
      `).join('');
    }

    const imgHtml = extDetails.image_url_medium 
      ? `<div class="text-center p-3 border rounded bg-white mb-3">
           <img src="${extDetails.image_url_medium}" class="img-fluid" style="max-height: 180px; object-fit: contain;" alt="Part preview">
         </div>`
      : '';

    container.innerHTML = `
      <div class="row g-4">
        <div class="col-md-4">
          ${imgHtml}
          <div class="list-group list-group-flush border rounded">
            <div class="list-group-item d-flex justify-content-between align-items-center">
              <span class="text-muted small">LCSC Part:</span>
              <span class="fw-bold">C${extDetails.lcsc}</span>
            </div>
            <div class="list-group-item d-flex justify-content-between align-items-center">
              <span class="text-muted small">Library Type:</span>
              ${typeBadge}
            </div>
            <div class="list-group-item d-flex justify-content-between align-items-center">
              <span class="text-muted small">JLCPCB Stock:</span>
              <span class="badge bg-info text-dark">${(extDetails.stock || 0).toLocaleString()}</span>
            </div>
            <div class="list-group-item d-flex justify-content-between align-items-center">
              <span class="text-muted small">Solder Joints:</span>
              <span>${extDetails.joints || '-'}</span>
            </div>
          </div>
          <div class="mt-3 d-grid gap-2">
            ${extDetails.datasheet ? `<a href="${extDetails.datasheet}" target="_blank" class="btn btn-outline-danger btn-sm">Datasheet (PDF)</a>` : ''}
            ${extDetails.lcsc_url ? `<a href="${extDetails.lcsc_url}" target="_blank" class="btn btn-outline-primary btn-sm">View on LCSC.com</a>` : ''}
          </div>
        </div>
        <div class="col-md-8">
          ${priceRows ? `
            <div class="mb-4">
              <h6 class="fw-bold text-secondary mb-2">Tiered Pricing (USD)</h6>
              <div class="table-responsive">
                <table class="table table-sm table-bordered text-center align-middle mb-0">
                  <thead class="table-light"><tr><th>Quantity Break</th><th>Unit Price</th></tr></thead>
                  <tbody>${priceRows}</tbody>
                </table>
              </div>
            </div>
          ` : ''}

          <div>
            <h6 class="fw-bold text-secondary mb-2">Technical Attributes</h6>
            ${attrRows ? `
              <div class="table-responsive border rounded">
                <table class="table table-sm table-hover mb-0">
                  <tbody>${attrRows}</tbody>
                </table>
              </div>
            ` : '<p class="text-muted small mb-0">No technical attributes recorded.</p>'}
          </div>
        </div>
      </div>
    `;

  } else if (src === 'altium') {
    // Altium details
    const isBasic = extDetails.basic_part === 1;
    const typeBadge = isBasic ? '<span class="badge bg-success">Basic Part</span>' : '<span class="badge bg-secondary">Extended Part</span>';

    let paramRows = '';
    const params = extDetails.parameters || {};
    const paramKeys = Object.keys(params);
    if (paramKeys.length > 0) {
      paramRows = paramKeys.map(k => `
        <tr>
          <th class="text-muted" style="width: 35%;">${escapeHtml(k)}</th>
          <td>${escapeHtml(params[k])}</td>
        </tr>
      `).join('');
    }

    container.innerHTML = `
      <div class="row g-4">
        <div class="col-md-6">
          <div class="card border-0 bg-light mb-3">
            <div class="card-body">
              <h6 class="fw-bold text-secondary mb-3">Component Specifications</h6>
              <div class="row g-2 small">
                <div class="col-6 text-muted">Library Reference:</div><div class="col-6 fw-bold">${escapeHtml(extDetails.lib_reference || '-')}</div>
                <div class="col-6 text-muted">LCSC Part #:</div><div class="col-6">${extDetails.lcsc_part ? `<span class="badge bg-light text-dark border">${escapeHtml(extDetails.lcsc_part)}</span>` : '-'}</div>
                <div class="col-6 text-muted">Category:</div><div class="col-6">${escapeHtml(extDetails.category_localized || extDetails.category || '-')}</div>
                <div class="col-6 text-muted">Package:</div><div class="col-6"><code>${escapeHtml(extDetails.package || '-')}</code></div>
                <div class="col-6 text-muted">Manufacturer:</div><div class="col-6">${escapeHtml(extDetails.manufacturer || '-')}</div>
                <div class="col-6 text-muted">Part Type:</div><div class="col-6">${typeBadge}</div>
                <div class="col-6 text-muted">Source Library File:</div><div class="col-6 text-truncate" title="${escapeHtml(extDetails.source_file || '')}"><code>${escapeHtml(extDetails.source_file || '-')}</code></div>
              </div>
            </div>
          </div>

          <div class="card border-0 bg-light mb-3">
            <div class="card-body">
              <h6 class="fw-bold text-secondary mb-3">Electrical Ratings</h6>
              <div class="row g-2 small">
                <div class="col-6 text-muted">Resistance:</div><div class="col-6">${escapeHtml(extDetails.resistance || '-')}</div>
                <div class="col-6 text-muted">Capacitance:</div><div class="col-6">${escapeHtml(extDetails.capacitance || '-')}</div>
                <div class="col-6 text-muted">Inductance:</div><div class="col-6">${escapeHtml(extDetails.inductance || '-')}</div>
                <div class="col-6 text-muted">Tolerance:</div><div class="col-6">${escapeHtml(extDetails.tolerance || '-')}</div>
                <div class="col-6 text-muted">Voltage Rating:</div><div class="col-6">${escapeHtml(extDetails.voltage_rating || '-')}</div>
                <div class="col-6 text-muted">Power Rating:</div><div class="col-6">${escapeHtml(extDetails.power_rating || '-')}</div>
              </div>
            </div>
          </div>

          <div class="d-flex flex-wrap gap-2">
            ${extDetails.datasheet_url ? `<a href="${extDetails.datasheet_url}" target="_blank" class="btn btn-outline-danger btn-sm">Datasheet</a>` : ''}
            ${extDetails.jlcpcb_url ? `<a href="${extDetails.jlcpcb_url}" target="_blank" class="btn btn-outline-primary btn-sm">JLCPCB</a>` : ''}
            ${extDetails.lcsc_url ? `<a href="${extDetails.lcsc_url}" target="_blank" class="btn btn-outline-secondary btn-sm">LCSC</a>` : ''}
          </div>
        </div>

        <div class="col-md-6">
          <h6 class="fw-bold text-secondary mb-2">Detailed Parameters</h6>
          ${paramRows ? `
            <div class="table-responsive border rounded" style="max-height: 400px; overflow-y: auto;">
              <table class="table table-sm table-hover mb-0">
                <tbody>${paramRows}</tbody>
              </table>
            </div>
          ` : '<p class="text-muted small">No extra parameters recorded.</p>'}
        </div>
      </div>
    `;

  } else if (src === 'kicad') {
    // KiCad details
    let propRows = '';
    const props = extDetails.properties || {};
    const propKeys = Object.keys(props);
    if (propKeys.length > 0) {
      propRows = propKeys.map(k => `
        <tr>
          <th class="text-muted" style="width: 35%;">${escapeHtml(k)}</th>
          <td>${escapeHtml(props[k])}</td>
        </tr>
      `).join('');
    }

    container.innerHTML = `
      <div class="row g-4">
        <div class="col-md-6">
          <div class="card border-0 bg-light mb-3">
            <div class="card-body">
              <h6 class="fw-bold text-secondary mb-3">Symbol Information</h6>
              <div class="row g-2 small">
                <div class="col-6 text-muted">Symbol Name:</div><div class="col-6 fw-bold">${escapeHtml(extDetails.name || '-')}</div>
                <div class="col-6 text-muted">Value:</div><div class="col-6">${escapeHtml(extDetails.value || '-')}</div>
                <div class="col-6 text-muted">Library:</div><div class="col-6"><span class="badge bg-light text-dark border">${escapeHtml(extDetails.library || '-')}</span></div>
                <div class="col-6 text-muted">Reference Prefix:</div><div class="col-6"><code>${escapeHtml(extDetails.reference || '-')}</code></div>
                <div class="col-6 text-muted">Default Footprint:</div><div class="col-6"><code>${escapeHtml(extDetails.footprint || '-')}</code></div>
                <div class="col-6 text-muted">Pin Count:</div><div class="col-6"><span class="badge bg-secondary">${extDetails.pin_count || 0}</span></div>
                <div class="col-6 text-muted">Keywords:</div><div class="col-6 text-muted">${escapeHtml(extDetails.keywords || '-')}</div>
              </div>
            </div>
          </div>

          ${propRows ? `
            <div class="mb-3">
              <h6 class="fw-bold text-secondary mb-2">Symbol Properties</h6>
              <div class="table-responsive border rounded" style="max-height: 250px; overflow-y: auto;">
                <table class="table table-sm table-hover mb-0">
                  <tbody>${propRows}</tbody>
                </table>
              </div>
            </div>
          ` : ''}

          ${extDetails.datasheet && extDetails.datasheet !== '~' ? `
            <a href="${extDetails.datasheet}" target="_blank" class="btn btn-outline-danger btn-sm">Datasheet (External)</a>
          ` : ''}
        </div>

        <div class="col-md-6">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <h6 class="fw-bold text-secondary mb-0">KiCad S-Expression</h6>
            <button class="btn btn-outline-secondary btn-sm" id="copySExprBtn">Copy S-Expression</button>
          </div>
          <pre class="bg-dark text-light p-3 rounded" style="max-height: 450px; overflow-y: auto; font-size: 0.82rem;"><code id="kicadSExpr">${escapeHtml(extDetails.raw_sexpr || 'No S-expression data available.')}</code></pre>
        </div>
      </div>
    `;

    const copyBtn = document.getElementById("copySExprBtn");
    if (copyBtn && extDetails.raw_sexpr) {
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(extDetails.raw_sexpr).then(() => {
          const original = copyBtn.textContent;
          copyBtn.textContent = 'Copied!';
          copyBtn.className = 'btn btn-success btn-sm';
          setTimeout(() => {
            copyBtn.textContent = original;
            copyBtn.className = 'btn btn-outline-secondary btn-sm';
          }, 2000);
        });
      });
    }
  } else if (src === 'fasteners') {
    const standard = extDetails.standard || {};
    const variant = extDetails.selected_variant || {};
    const dimensions = variant.dimensions || {};
    const dimensionRows = Object.entries(dimensions).map(([name, value]) => `
      <tr>
        <th class="text-muted" style="width: 40%;">${escapeHtml(name)}</th>
        <td>${escapeHtml(value)}</td>
      </tr>
    `).join('');
    const standardCode = variant.standard_code || standard.standard_code || '-';
    const length = variant.length
      ? `${variant.length}${String(variant.length).toLowerCase().includes('in') ? '' : ' mm'}`
      : '-';

    container.innerHTML = `
      <div class="row g-4">
        <div class="col-md-5">
          <div class="card border-0 bg-light h-100">
            <div class="card-body">
              <h6 class="fw-bold text-secondary mb-3">${escapeHtml(standard.standard_name || standardCode)}</h6>
              <div class="row g-2 small">
                <div class="col-5 text-muted">${escapeHtml(I18N.fastener_standard || 'Standard')}</div>
                <div class="col-7 fw-bold">${escapeHtml(standardCode)}</div>
                <div class="col-5 text-muted">${escapeHtml(I18N.fastener_nominal || 'Nominal size')}</div>
                <div class="col-7">${escapeHtml(variant.nominal || '-')}</div>
                ${standard.has_length ? `
                  <div class="col-5 text-muted">${escapeHtml(I18N.fastener_length || 'Length')}</div>
                  <div class="col-7">${escapeHtml(length)}</div>
                ` : ''}
                <div class="col-5 text-muted">${escapeHtml(I18N.source_fasteners || 'Mechanical Standards')}</div>
                <div class="col-7">${escapeHtml(standard.authority || '-')}</div>
              </div>
              ${standard.description ? `<p class="text-muted small mt-3 mb-0">${escapeHtml(standard.description)}</p>` : ''}
            </div>
          </div>
        </div>
        <div class="col-md-7">
          <h6 class="fw-bold text-secondary mb-2">${escapeHtml(I18N.fastener_dimensions || 'Selected dimensions')}</h6>
          ${dimensionRows ? `
            <div class="table-responsive border rounded">
              <table class="table table-sm table-hover mb-0"><tbody>${dimensionRows}</tbody></table>
            </div>
          ` : `<p class="text-muted small">${escapeHtml(I18N.fastener_no_dimensions || 'No additional dimensions recorded.')}</p>`}
        </div>
      </div>
    `;
  }
}

// Fetch part details
fetch(`/api/inventory/get_part_by_id?part_id=${partId}`)
  .then(res => {
    if (!res.ok) throw new Error(I18N.alert_fetch_failed);
    return res.json();
  })
  .then(data => {
    // Header & identity
    document.getElementById("part-id").textContent = `#${data.id}`;
    document.getElementById("part-name").textContent = data.name || '-';
    document.getElementById("part-manufacturer").textContent = data.manufacturer || '-';
    document.getElementById("part-type").textContent = data.part_type || '-';
    document.getElementById("part-package").textContent = data.package || '-';
    document.getElementById("part-quantity").textContent = (data.quantity !== null && data.quantity !== undefined) ? data.quantity : 0;
    const warehouseLink = document.getElementById("warehouse-placement-link");
    warehouseLink.href = `/warehouse?part_id=${encodeURIComponent(partId)}`;
    warehouseLink.classList.toggle("d-none", data.quantity <= 0 && data.warehouse_status !== "in_warehouse");
    warehouseLink.textContent = data.warehouse_status === "in_warehouse" ? I18N.warehouse_view : I18N.warehouse_place;
    document.getElementById("part-description").textContent = data.description || (I18N.no_description || 'No description provided.');
    
    // Storage location & note
    document.getElementById("part-location").textContent = data.storage_location || 'Default Storage';
    document.getElementById("part-note").textContent = data.note || '-';
    
    // Pre-fill edit inputs
    const locInput = document.getElementById("editLocationInput");
    if (locInput) locInput.value = data.storage_location || '';
    const noteInput = document.getElementById("editNoteInput");
    if (noteInput) noteInput.value = data.note || '';

    // Source Library badge & External Reference button
    const src = (data.library_source || '').toLowerCase();
    const sourceBadge = document.getElementById("source-library-badge");
    const sourceText = document.getElementById("source-lib-text");
    const viewInLibBtn = document.getElementById("view-in-library-btn");

    if (src === 'altium') {
      sourceBadge.className = 'badge bg-dark';
      sourceBadge.textContent = 'Altium';
      sourceText.textContent = `Altium JLCPCB (ID: ${data.external_part_id})`;
      viewInLibBtn.href = `/libraries/altium/${data.external_part_id}`;
      viewInLibBtn.classList.remove('d-none');
    } else if (src === 'kicad') {
      sourceBadge.className = 'badge bg-secondary';
      sourceBadge.textContent = 'KiCad';
      sourceText.textContent = `KiCad Symbols (ID: ${data.external_part_id})`;
      viewInLibBtn.href = `/libraries/kicad/${data.external_part_id}`;
      viewInLibBtn.classList.remove('d-none');
    } else if (src === 'jlcparts') {
      sourceBadge.className = 'badge bg-primary';
      sourceBadge.textContent = 'JLCParts';
      const lcscId = String(data.external_part_id).replace('C', '');
      sourceText.textContent = `JLCParts (C${lcscId})`;
      viewInLibBtn.href = `/libraries/jlcparts/${lcscId}`;
      viewInLibBtn.classList.remove('d-none');
    } else if (src === 'fasteners') {
      const variant = data.external_details?.selected_variant || {};
      const standard = data.external_details?.standard || {};
      const standardCode = variant.standard_code || standard.standard_code || '';
      sourceBadge.className = 'badge bg-secondary';
      sourceBadge.textContent = I18N.source_fasteners || 'Mechanical Standards';
      sourceText.textContent = `${standardCode} ${variant.nominal || ''}${variant.length ? ` × ${variant.length}` : ''}`.trim();
      if (standardCode) {
        viewInLibBtn.href = `/libraries/fasteners/${encodeURIComponent(standardCode)}`;
        viewInLibBtn.classList.remove('d-none');
      }
    } else {
      sourceBadge.textContent = src || 'External';
      sourceText.textContent = `${src} (#${data.external_part_id})`;
    }

    // In stock status
    const quantity = data.quantity || 0;
    const inStockSpan = document.getElementById('in-stock-status');
    if (quantity > 0) {
      inStockSpan.textContent = I18N.status_in_stock || 'In Stock';
      inStockSpan.className = 'badge bg-success';
    } else {
      inStockSpan.textContent = I18N.status_out_of_stock || 'Out of Stock';
      inStockSpan.className = 'badge bg-danger';
    }

    // Associated projects
    const projectsContainer = document.getElementById("part-projects");
    if (projectsContainer) {
      if (data.projects && data.projects.length > 0) {
        projectsContainer.innerHTML = data.projects.map(p => `
          <div class="d-flex justify-content-between align-items-center mb-2 p-2 border rounded bg-light">
            <div>
              <a href="/project_details?project_id=${p.id}" class="fw-bold text-decoration-none">${escapeHtml(p.name)}</a>
            </div>
            <div>
              <span class="text-muted small me-1">${I18N.quantity_needed_label || 'Needed'}:</span>
              <span class="badge bg-primary">${p.quantity_needed || 0}</span>
            </div>
          </div>
        `).join('');
      } else {
        projectsContainer.innerHTML = `
          <p class="text-muted mb-2">${I18N.no_projects_desc || 'This part is not associated with any project (loose part).'}</p>
          <span class="badge bg-light text-muted border">${I18N.badge_loose_part || 'Loose Part'}</span>
        `;
      }
    }

    // Render external specs card
    renderExternalSpecs(data.library_source, data.external_details, data);
  })
  .catch(error => {
    console.error(I18N.alert_fetch_failed, error);
    alert(I18N.alert_fetch_failed || 'Error fetching component details');
  });

// Update Storage Location & Notes
function updateMeta() {
  const locVal = document.getElementById('editLocationInput').value.trim();
  const noteVal = document.getElementById('editNoteInput').value.trim();

  fetch('/api/inventory/update_meta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      part_id: parseInt(partId),
      storage_location: locVal || 'Default Storage',
      note: noteVal || ''
    })
  })
  .then(res => {
    if (!res.ok) throw new Error('Failed to update location and note');
    return res.json();
  })
  .then(updated => {
    document.getElementById("part-location").textContent = updated.storage_location || 'Default Storage';
    document.getElementById("part-note").textContent = updated.note || '-';
    alert(I18N.alert_update_meta_success || 'Location and notes updated successfully!');
  })
  .catch(err => {
    console.error(err);
    alert(err.message || 'Error updating metadata');
  });
}

const saveMetaBtn = document.getElementById('saveMetaBtn');
if (saveMetaBtn) {
  saveMetaBtn.addEventListener('click', updateMeta);
}

// Update Quantity
function updateQuantity() {
  const inputVal = document.getElementById('updateQuantity').value.trim();
  const delta = parseInt(inputVal, 10);
  if (isNaN(delta) || delta === 0) {
    alert(I18N.alert_invalid_quantity || 'Please enter a valid quantity');
    return;
  }

  fetch('/api/inventory/update_quantity', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      part_id: parseInt(partId),
      quantity: delta
    })
  })
  .then(response => {
    if (!response.ok) {
      return response.json().then(err => { throw new Error(err.detail || I18N.alert_update_failed); });
    }
    return response.json();
  })
  .then(data => {
    location.reload(); 
  })
  .catch(error => {
    console.error('Error:', error);
    alert(error.message || I18N.alert_update_failed);
  });
}

// Delete Part
function deletePart() {
  if (!window.confirm(I18N.confirm_delete || 'Are you sure you want to delete this part?')) return; 

  fetch(`/api/inventory/delete_part?part_id=${partId}`, {
    method: 'DELETE'
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(I18N.alert_delete_failed);
    }
    return response.json();
  })
  .then(() => {
    window.location.href = "/inventory";
  })
  .catch(error => {
    console.error('Error:', error);
    alert(I18N.alert_delete_failed || 'Failed to delete part');
  });
}

document.getElementById('updateQuantityBtn').addEventListener('click', updateQuantity);
document.getElementById('deletePartBtn').addEventListener('click', deletePart);
document.getElementById('viewHistoryBtn').addEventListener('click', () => {
  window.location.href = `/project-history?part_id=${encodeURIComponent(partId)}`;
});
document.getElementById('exportDetailsBtn').addEventListener('click', () => alert(I18N.export_coming_soon || 'Coming soon'));
