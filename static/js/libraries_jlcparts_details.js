const lcscNum = document.getElementById('detailContainer')?.dataset?.lcsc || window.location.pathname.split('/').filter(Boolean).pop();
      const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');

      async function loadComponentDetails() {
        try {
          const res = await fetch(`/api/libraries/jlcparts/${lcscNum}`);
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

        document.getElementById('mfrPartNumber').textContent = data.mfr || `C${data.lcsc}`;
        document.getElementById('lcscBadge').textContent = `C${data.lcsc}`;
        document.getElementById('manufacturerName').textContent = data.manufacturer || '';

        // Actions
        const actionsContainer = document.getElementById('headerActions');
        actionsContainer.innerHTML = `
          <button class="btn btn-success btn-sm text-nowrap" onclick="openImportModal('jlcparts', '${data.lcsc}', 'C${data.lcsc} (${escapeHtml(data.mfr || '')})', '${escapeHtml(data.package || '')} | ${escapeHtml(data.category || '')}')">
            ${i18n.btn_quick_add || '+ Add to Inventory'}
          </button>
        `;

        // Badges
        const badges = document.getElementById('headerBadges');
        badges.innerHTML = '';
        if (data.library_type === 'base') {
          badges.innerHTML += `<span class="badge bg-success">${i18n.badge_basic || 'Basic Part'}</span>`;
        } else if (data.preferred === 1) {
          badges.innerHTML += `<span class="badge bg-info text-dark">${i18n.badge_preferred || 'Preferred'}</span>`;
        } else {
          badges.innerHTML += `<span class="badge bg-secondary">${i18n.badge_extended || 'Expand Part'}</span>`;
        }
        if (data.stock > 0) {
          badges.innerHTML += `<span class="badge bg-success">${i18n.badge_in_stock || 'In Stock'}: ${data.stock.toLocaleString()}</span>`;
        } else if (data.stock < 0) {
          badges.innerHTML += `<span class="badge bg-secondary">${i18n.stock_unknown || 'Stock unknown'}</span>`;
        } else {
          badges.innerHTML += `<span class="badge bg-secondary">${i18n.badge_out_of_stock || 'Out of Stock'}</span>`;
        }
        if (data.rohs === 1) {
          badges.innerHTML += `<span class="badge bg-outline-success border border-success text-success">RoHS Compliant</span>`;
        }

        // Image
        const imgContainer = document.getElementById('imageContainer');
        if (data.image_url_medium) {
          imgContainer.innerHTML = `
            <a href="${data.image_url_large || data.image_url_medium}" target="_blank" rel="noopener noreferrer">
              <img src="${data.image_url_medium}" alt="${escapeHtml(data.mfr)}" class="img-fluid rounded" style="max-height: 220px; object-fit: contain;">
            </a>`;
        }

        // Pricing Table
        const pricingTbody = document.getElementById('pricingTableBody');
        pricingTbody.innerHTML = '';
        if (data.price_breaks && data.price_breaks.length > 0) {
          data.price_breaks.forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td>${escapeHtml(p.range)}</td>
              <td class="fw-bold text-success">$${escapeHtml(p.price)}</td>
            `;
            pricingTbody.appendChild(tr);
          });
        } else {
          pricingTbody.innerHTML = `<tr><td colspan="2" class="text-muted py-2">No pricing available</td></tr>`;
        }

        // Summary
        document.getElementById('propLcsc').textContent = `C${data.lcsc}`;
        document.getElementById('propMfr').textContent = data.mfr || '-';
        document.getElementById('propManufacturer').textContent = data.manufacturer || '-';
        const catLocalized = data.category_localized || data.category;
        const subcatLocalized = data.subcategory_localized || data.subcategory;
        document.getElementById('propCategory').textContent = data.category ? (catLocalized && catLocalized !== data.category ? `${catLocalized} (${data.category})` : (catLocalized || data.category)) : '-';
        document.getElementById('propSubcategory').textContent = data.subcategory ? (subcatLocalized && subcatLocalized !== data.subcategory ? `${subcatLocalized} (${data.subcategory})` : (subcatLocalized || data.subcategory)) : '-';
        document.getElementById('propPackage').textContent = data.package || '-';
        document.getElementById('propJoints').textContent = data.joints || '-';
        document.getElementById('propStock').innerHTML = data.stock < 0 ?
          `<span class="text-muted">${i18n.stock_unknown || '-'}</span>` : data.stock > 0 ?
            `<span class="text-success fw-bold">${data.stock.toLocaleString()}</span>` :
            `<span class="text-muted">0</span>`;
        document.getElementById('propLibraryType').textContent = data.library_type || '-';

        // Manufacturing
        document.getElementById('propRohs').innerHTML = data.rohs === 1 ?
          '<span class="badge bg-success">Yes (RoHS)</span>' : '<span class="badge bg-secondary">No / Unknown</span>';
        document.getElementById('propAssemblyProcess').textContent = data.assembly_process || '-';
        document.getElementById('propAssemblyMode').textContent = data.assembly_mode || '-';
        document.getElementById('propEccn').textContent = data.eccn || '-';
        document.getElementById('propDescription').textContent = data.description || '-';

        // External Links
        const linksContainer = document.getElementById('linksContainer');
        linksContainer.innerHTML = '';
        if (data.datasheet) {
          linksContainer.innerHTML += `
            <a href="${data.datasheet}" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm">
              ${i18n.prop_datasheet || 'Datasheet (PDF)'}
            </a>`;
        }
        if (data.lcsc_url) {
          linksContainer.innerHTML += `
            <a href="${data.lcsc_url}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-primary btn-sm">
              ${i18n.prop_lcsc_link || 'View on LCSC'}
            </a>`;
        }
        if (!linksContainer.children.length) {
          document.getElementById('linksCard').style.display = 'none';
        }

        // Attributes Table
        const attrTbody = document.getElementById('attributesTableBody');
        attrTbody.innerHTML = '';
        const attrs = data.attributes_dict || {};
        const attrKeys = Object.keys(attrs);
        document.getElementById('attributesCountBadge').textContent = attrKeys.length;

        if (attrKeys.length === 0) {
          attrTbody.innerHTML = `<tr><td colspan="2" class="text-center text-muted py-3">${i18n.no_data || 'No attributes available'}</td></tr>`;
        } else {
          attrKeys.forEach(k => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td class="fw-bold text-secondary">${escapeHtml(k)}</td>
              <td>${escapeHtml(String(attrs[k]))}</td>
            `;
            attrTbody.appendChild(tr);
          });
        }
      }

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      loadComponentDetails();
