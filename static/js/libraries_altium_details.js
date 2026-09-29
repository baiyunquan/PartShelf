const compId = document.getElementById('detailContainer')?.dataset?.compId || window.location.pathname.split('/').filter(Boolean).pop();
      const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');

      async function loadComponentDetails() {
        try {
          const res = await fetch(`/api/libraries/altium/${compId}`);
          if (!res.ok) throw new Error('Not found');
          const data = await res.json();
          renderDetails(data);
        } catch (e) {
          document.getElementById('loadingContainer').innerHTML =
            `<div class="alert alert-danger">${i18n.no_data || 'Component not found.'}</div>`;
        }
      }

      function renderDetails(data) {
        document.getElementById('loadingContainer').style.display = 'none';
        document.getElementById('contentContainer').style.display = 'block';

        document.getElementById('libReference').textContent = data.lib_reference || '-';
        document.getElementById('mfrPartNumber').textContent = data.mfr_part_number || data.lib_reference || '';

        // Actions
        const actionsContainer = document.getElementById('headerActions');
        actionsContainer.innerHTML = `
          <button class="btn btn-success btn-sm text-nowrap" onclick="openImportModal('altium', '${data.id}', '${escapeHtml(data.lib_reference)}', '${escapeHtml(data.package || '')} | ${escapeHtml(data.manufacturer || '')}')">
            ${i18n.btn_quick_add || '+ Add to Inventory'}
          </button>
        `;

        // Badges
        const badges = document.getElementById('headerBadges');
        badges.innerHTML = '';
        if (data.basic_part === 1) {
          badges.innerHTML += `<span class="badge bg-success">${i18n.badge_basic || 'Basic Part'}</span>`;
        } else {
          badges.innerHTML += `<span class="badge bg-secondary">${i18n.badge_extended || 'Extended Part'}</span>`;
        }
        if (data.category) {
          const catLocalized = data.category_localized || data.category;
          badges.innerHTML += `<span class="badge bg-info text-dark" title="${escapeHtml(data.category)}">${escapeHtml(catLocalized)}</span>`;
        }
        if (data.package) {
          badges.innerHTML += `<span class="badge bg-dark">${escapeHtml(data.package)}</span>`;
        }
        if (data.manufacturer) {
          badges.innerHTML += `<span class="badge bg-light text-dark border">${escapeHtml(data.manufacturer)}</span>`;
        }

        // Basic
        document.getElementById('propLibRef').textContent = data.lib_reference || '-';
        document.getElementById('propLcsc').innerHTML = data.lcsc_part ?
          `<span class="badge bg-light text-dark border">${escapeHtml(data.lcsc_part)}</span>` : '-';
        const catLocalized = data.category_localized || data.category;
        document.getElementById('propCategory').textContent = data.category ? (catLocalized && catLocalized !== data.category ? `${catLocalized} (${data.category})` : (catLocalized || data.category)) : '-';
        document.getElementById('propPackage').textContent = data.package || '-';
        document.getElementById('propManufacturer').textContent = data.manufacturer || '-';
        document.getElementById('propSourceFile').textContent = data.source_file || '-';

        // Specs
        document.getElementById('propResistance').textContent = data.resistance || '-';
        document.getElementById('propCapacitance').textContent = data.capacitance || '-';
        document.getElementById('propInductance').textContent = data.inductance || '-';
        document.getElementById('propTolerance').textContent = data.tolerance || '-';
        document.getElementById('propVoltage').textContent = data.voltage_rating || '-';
        document.getElementById('propPower').textContent = data.power_rating || '-';
        document.getElementById('propDescription').textContent = data.description || '-';

        // Links
        const linksContainer = document.getElementById('linksContainer');
        linksContainer.innerHTML = '';
        if (data.datasheet_url) {
          linksContainer.innerHTML += `
            <a href="${data.datasheet_url}" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">
              ${i18n.external_datasheet || 'Datasheet (PDF)'}
            </a>`;
        }
        if (data.jlcpcb_url) {
          linksContainer.innerHTML += `
            <a href="${data.jlcpcb_url}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-info btn-sm">
              ${i18n.external_jlcpcb || 'JLCPCB Page'}
            </a>`;
        }
        if (data.lcsc_url) {
          linksContainer.innerHTML += `
            <a href="${data.lcsc_url}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-secondary btn-sm">
              ${i18n.external_lcsc || 'LCSC Page'}
            </a>`;
        }
        if (!linksContainer.children.length) {
          document.getElementById('linksCard').style.display = 'none';
        }

        // Parameters Table
        const paramsTbody = document.getElementById('paramsTableBody');
        paramsTbody.innerHTML = '';
        const params = data.parameters || {};
        const keys = Object.keys(params);
        document.getElementById('paramsCountBadge').textContent = keys.length;

        if (keys.length === 0) {
          paramsTbody.innerHTML = `<tr><td colspan="2" class="text-center text-muted py-3">${i18n.no_data || 'No parameters available'}</td></tr>`;
        } else {
          keys.forEach(k => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td class="fw-bold text-secondary">${escapeHtml(k)}</td>
              <td>${escapeHtml(String(params[k]))}</td>
            `;
            paramsTbody.appendChild(tr);
          });
        }

        // Raw Data
        if (data.raw_data) {
          document.getElementById('rawCard').style.display = 'block';
          document.getElementById('rawJsonBlock').textContent = JSON.stringify(data.raw_data, null, 2);
        }
      }

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      loadComponentDetails();
