const I18N = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let currentQuery = (document.getElementById('centerSearchInput')?.value || '').trim();
      let activeTab = 'all';
      let currentPage = 1;
      let currentPageSize = 25;

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      function formatAltiumSpecs(item) {
        const parts = [];
        if (item.resistance) parts.push(item.resistance);
        if (item.capacitance) parts.push(item.capacitance);
        if (item.inductance) parts.push(item.inductance);
        if (item.tolerance) parts.push(item.tolerance);
        if (item.voltage_rating) parts.push(item.voltage_rating);
        if (item.power_rating) parts.push(item.power_rating);
        if (parts.length > 0) return parts.join(', ');
        return item.description ? (item.description.length > 35 ? item.description.substring(0, 33) + '...' : item.description) : '-';
      }

      function updateUrl() {
        const params = new URLSearchParams();
        if (currentQuery) params.set('q', currentQuery);
        if (activeTab && activeTab !== 'all') params.set('tab', activeTab);
        if (currentPage > 1) params.set('page', currentPage);
        const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.history.replaceState({}, '', newUrl);
      }

      async function executeSearch() {
        const inputVal = document.getElementById('centerSearchInput').value.trim();
        currentQuery = inputVal;
        updateUrl();

        document.getElementById('centerClearBtn').style.display = currentQuery ? 'inline-block' : 'none';

        if (!currentQuery) {
          document.getElementById('searchMetaRow').style.display = 'none';
          document.getElementById('emptyResultBox').style.display = 'none';
          document.getElementById('view-all').style.display = 'none';
          document.getElementById('view-single').style.display = 'none';
          return;
        }

        document.getElementById('loadingIndicator').style.display = 'block';
        document.getElementById('emptyResultBox').style.display = 'none';

        try {
          const res = await fetch(`/api/search/aggregate?q=${encodeURIComponent(currentQuery)}&tab=${encodeURIComponent(activeTab)}&page=${currentPage}&page_size=${currentPageSize}`);
          const data = await res.json();
          renderResults(data);
        } catch (err) {
          console.error("Search error", err);
        } finally {
          document.getElementById('loadingIndicator').style.display = 'none';
        }
      }

      function renderResults(data) {
        document.getElementById('searchMetaRow').style.display = 'flex';
        document.getElementById('currentQueryLabel').textContent = currentQuery;

        if (activeTab === 'all') {
          renderAllOverview(data);
        } else {
          renderSingleTab(data);
        }
      }

      function renderAllOverview(data) {
        document.getElementById('view-all').style.display = 'block';
        document.getElementById('view-single').style.display = 'none';

        const counts = data.counts || {};
        const total = data.total_matches || 0;
        document.getElementById('totalMatchesLabel').textContent = `${total.toLocaleString()} records`;

        document.getElementById('badge-all').textContent = total.toLocaleString();
        document.getElementById('badge-inventory').textContent = (counts.inventory || 0).toLocaleString();
        document.getElementById('badge-jlcparts').textContent = (counts.jlcparts || 0).toLocaleString();
        document.getElementById('badge-altium').textContent = (counts.altium || 0).toLocaleString();
        document.getElementById('badge-kicad').textContent = (counts.kicad || 0).toLocaleString();
        document.getElementById('badge-fasteners').textContent = (counts.fasteners || 0).toLocaleString();

        document.getElementById('all-inv-count').textContent = (counts.inventory || 0).toLocaleString();
        document.getElementById('all-jlc-count').textContent = (counts.jlcparts || 0).toLocaleString();
        document.getElementById('all-altium-count').textContent = (counts.altium || 0).toLocaleString();
        document.getElementById('all-kicad-count').textContent = (counts.kicad || 0).toLocaleString();
        document.getElementById('all-fasteners-count').textContent = (counts.fasteners || 0).toLocaleString();

        if (total === 0) {
          document.getElementById('emptyResultBox').style.display = 'block';
          document.getElementById('view-all').style.display = 'none';
          return;
        }

        // 1. Inventory Preview
        const invBody = document.getElementById('overview-inventory-body');
        invBody.innerHTML = '';
        const invItems = data.inventory?.items || [];
        if (invItems.length === 0) {
          invBody.innerHTML = `<tr><td colspan="6" class="text-center py-3 text-muted">No inventory matches</td></tr>`;
        } else {
          invItems.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td><span class="badge bg-light text-dark border">#${item.id}</span></td>
              <td>
                <a href="${item.url}" class="fw-bold text-decoration-none text-primary">${escapeHtml(item.name)}</a>
                <small class="text-muted d-block">${escapeHtml(item.manufacturer || '-')}</small>
              </td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.storage_location || 'Default Storage')}</span></td>
              <td><span class="badge ${item.quantity > 0 ? 'bg-success' : 'bg-danger'}">${item.quantity}</span></td>
              <td class="text-end">
                <a href="${item.url}" class="btn btn-outline-primary btn-sm">${I18N.btn_details || 'Details'}</a>
              </td>
            `;
            invBody.appendChild(tr);
          });
        }

        // 2. JLCParts Preview
        const jlcBody = document.getElementById('overview-jlcparts-body');
        jlcBody.innerHTML = '';
        const jlcItems = data.jlcparts?.items || [];
        if (jlcItems.length === 0) {
          jlcBody.innerHTML = `<tr><td colspan="10" class="text-center py-3 text-muted">No JLCPCB matches</td></tr>`;
        } else {
          jlcItems.forEach(item => {
            const tr = document.createElement('tr');
            let imgHtml = '<div class="bg-light rounded d-flex align-items-center justify-content-center text-muted border part-thumb" style="font-size:0.6rem;">IC</div>';
            if (item.image_url_small) {
              imgHtml = `<img src="${item.image_url_small}" class="rounded border part-thumb" loading="lazy" onerror="this.outerHTML='<div class=\\'bg-light rounded d-flex align-items-center justify-content-center text-muted border part-thumb\\' style=\\'font-size:0.6rem;\\'>IC</div>'">`;
            }
            const price = item.price_breaks && item.price_breaks[0] ? `$${item.price_breaks[0].price}` : '-';
            tr.innerHTML = `
              <td>${imgHtml}</td>
              <td><strong class="text-dark">${escapeHtml(item.specs || '-')}</strong></td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td>
                <a href="/libraries/jlcparts/${item.lcsc}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.mfr || '-')}</a>
              </td>
              <td>
                <small class="d-block fw-bold text-dark">${escapeHtml(item.category_localized || item.category || '-')}</small>
                <small class="text-secondary">${escapeHtml(item.subcategory_localized || item.subcategory || '')}</small>
              </td>
              <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
              <td><a href="/libraries/jlcparts/${item.lcsc}" class="badge bg-light text-dark border text-decoration-none fw-bold">C${item.lcsc}</a></td>
              <td><span class="${item.stock > 0 ? 'text-success fw-bold' : 'text-muted'}">${item.stock > 0 ? item.stock.toLocaleString() : '0'}</span></td>
              <td><small class="fw-bold text-dark">${price}</small></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('jlcparts', '${item.lcsc}', 'C${item.lcsc} (${escapeHtml(item.mfr || '')})', '${escapeHtml(item.package || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/jlcparts/${item.lcsc}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            if (item.source === 'lcsc_dynamic') {
              const sourceBadge = document.createElement('span');
              sourceBadge.className = 'badge bg-warning text-dark';
              sourceBadge.textContent = I18N.badge_lcsc_dynamic || 'LCSC Dynamic';
              tr.querySelector('td:nth-child(4)').appendChild(sourceBadge);
            }
            jlcBody.appendChild(tr);
          });
        }

        // 3. Altium Preview
        const altiumBody = document.getElementById('overview-altium-body');
        altiumBody.innerHTML = '';
        const altiumItems = data.altium?.items || [];
        if (altiumItems.length === 0) {
          altiumBody.innerHTML = `<tr><td colspan="7" class="text-center py-3 text-muted">No Altium matches</td></tr>`;
        } else {
          altiumItems.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td><strong class="text-dark">${escapeHtml(formatAltiumSpecs(item))}</strong></td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td>
                <a href="/libraries/altium/${item.id}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.lib_reference || '-')}</a>
              </td>
              <td><small class="text-secondary">${escapeHtml(item.category_localized || item.category || '-')}</small></td>
              <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.lcsc_part || '-')}</span></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('altium', '${item.id}', '${escapeHtml(item.lib_reference || '')}', '${escapeHtml(item.package || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/altium/${item.id}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            altiumBody.appendChild(tr);
          });
        }

        // 4. KiCad Preview
        const kicadBody = document.getElementById('overview-kicad-body');
        kicadBody.innerHTML = '';
        const kicadItems = data.kicad?.items || [];
        if (kicadItems.length === 0) {
          kicadBody.innerHTML = `<tr><td colspan="4" class="text-center py-3 text-muted">No KiCad matches</td></tr>`;
        } else {
          kicadItems.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td>
                <a href="/libraries/kicad/${item.id}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.name || item.value || '-')}</a>
                <small class="text-muted">${escapeHtml(item.description || '')}</small>
              </td>
              <td><span class="badge bg-secondary">${escapeHtml(item.library || '-')}</span></td>
              <td><code>${escapeHtml(item.footprint || '-')}</code></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('kicad', '${item.id}', '${escapeHtml(item.name || '')}', '${escapeHtml(item.library || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/kicad/${item.id}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            kicadBody.appendChild(tr);
          });
        }

        // 5. Fasteners Preview
        const fastenersBody = document.getElementById('overview-fasteners-body');
        fastenersBody.innerHTML = '';
        const fastenersItems = data.fasteners?.items || [];
        if (fastenersItems.length === 0) {
          fastenersBody.innerHTML = `<tr><td colspan="5" class="text-center py-3 text-muted">No Fastener matches</td></tr>`;
        } else {
          fastenersItems.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td>
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="fw-bold text-decoration-none text-primary">
                  ${escapeHtml(item.standard_code)}
                </a>
              </td>
              <td><span class="badge bg-secondary">${escapeHtml(item.authority || 'STD')}</span></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.category_group_zh || item.category_group || '-')}</span></td>
              <td>
                <small class="text-dark">${escapeHtml(item.description || item.standard_name || '-')}</small>
              </td>
              <td class="text-end">
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="btn btn-outline-primary btn-sm">详情</a>
              </td>
            `;
            fastenersBody.appendChild(tr);
          });
        }
      }

      function renderSingleTab(data) {
        document.getElementById('view-all').style.display = 'none';
        document.getElementById('view-single').style.display = 'block';

        const total = data.total || 0;
        document.getElementById('singleViewBadge').textContent = total.toLocaleString();

        const thead = document.getElementById('singleTableHeader');
        const tbody = document.getElementById('singleTableBody');
        tbody.innerHTML = '';

        if (total === 0) {
          document.getElementById('emptyResultBox').style.display = 'block';
          thead.innerHTML = '';
          return;
        }

        if (activeTab === 'inventory') {
          document.getElementById('singleViewTitle').textContent = I18N.tab_inventory || 'My Inventory';
          thead.innerHTML = `
            <tr>
              <th style="width: 70px;">${I18N.th_id || 'ID'}</th>
              <th>${I18N.th_name || 'Part Name'}</th>
              <th style="width: 140px;">${I18N.th_package || 'Package'}</th>
              <th style="width: 130px;">${I18N.th_location || 'Location'}</th>
              <th style="width: 100px;">${I18N.th_quantity || 'Quantity'}</th>
              <th style="width: 90px;" class="text-end">${I18N.th_actions || 'Actions'}</th>
            </tr>
          `;
          data.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td><span class="badge bg-light text-dark border">#${item.id}</span></td>
              <td>
                <a href="${item.url}" class="fw-bold text-decoration-none text-primary">${escapeHtml(item.name)}</a>
                <small class="text-muted d-block">${escapeHtml(item.manufacturer || '-')}</small>
              </td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.storage_location || 'Default Storage')}</span></td>
              <td><span class="badge ${item.quantity > 0 ? 'bg-success' : 'bg-danger'}">${item.quantity}</span></td>
              <td class="text-end">
                <a href="${item.url}" class="btn btn-outline-primary btn-sm">${I18N.btn_details || 'Details'}</a>
              </td>
            `;
            tbody.appendChild(tr);
          });
        } else if (activeTab === 'jlcparts') {
          document.getElementById('singleViewTitle').textContent = I18N.tab_jlcparts || 'JLCPCB Parts';
          thead.innerHTML = `
            <tr>
              <th style="width: 60px;">${I18N.th_image || 'Image'}</th>
              <th style="min-width: 150px;">${I18N.th_specs || 'Specs'}</th>
              <th style="width: 110px;">${I18N.th_package || 'Package'}</th>
              <th>${I18N.th_mfr || 'Part Number'}</th>
              <th style="min-width: 140px;">${I18N.th_category || 'Category'}</th>
              <th style="min-width: 110px;">${I18N.th_manufacturer || 'Manufacturer'}</th>
              <th style="width: 100px;">${I18N.th_lcsc || 'LCSC #'}</th>
              <th style="width: 90px;">${I18N.th_stock || 'Stock'}</th>
              <th style="width: 90px;">${I18N.th_price || 'Price'}</th>
              <th style="width: 150px;" class="text-end">${I18N.th_actions || 'Actions'}</th>
            </tr>
          `;
          data.items.forEach(item => {
            const tr = document.createElement('tr');
            let imgHtml = '<div class="bg-light rounded d-flex align-items-center justify-content-center text-muted border part-thumb" style="font-size:0.6rem;">IC</div>';
            if (item.image_url_small) {
              imgHtml = `<img src="${item.image_url_small}" class="rounded border part-thumb" loading="lazy" onerror="this.outerHTML='<div class=\\'bg-light rounded d-flex align-items-center justify-content-center text-muted border part-thumb\\' style=\\'font-size:0.6rem;\\'>IC</div>'">`;
            }
            const price = item.price_breaks && item.price_breaks[0] ? `$${item.price_breaks[0].price}` : '-';
            tr.innerHTML = `
              <td>${imgHtml}</td>
              <td><strong class="text-dark">${escapeHtml(item.specs || '-')}</strong></td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td>
                <a href="/libraries/jlcparts/${item.lcsc}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.mfr || '-')}</a>
              </td>
              <td>
                <small class="d-block fw-bold text-dark">${escapeHtml(item.category_localized || item.category || '-')}</small>
                <small class="text-secondary">${escapeHtml(item.subcategory_localized || item.subcategory || '')}</small>
              </td>
              <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
              <td><a href="/libraries/jlcparts/${item.lcsc}" class="badge bg-light text-dark border text-decoration-none fw-bold">C${item.lcsc}</a></td>
              <td><span class="${item.stock > 0 ? 'text-success fw-bold' : 'text-muted'}">${item.stock > 0 ? item.stock.toLocaleString() : '0'}</span></td>
              <td><small class="fw-bold text-dark">${price}</small></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('jlcparts', '${item.lcsc}', 'C${item.lcsc} (${escapeHtml(item.mfr || '')})', '${escapeHtml(item.package || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/jlcparts/${item.lcsc}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            if (item.source === 'lcsc_dynamic') {
              const sourceBadge = document.createElement('span');
              sourceBadge.className = 'badge bg-warning text-dark';
              sourceBadge.textContent = I18N.badge_lcsc_dynamic || 'LCSC Dynamic';
              tr.querySelector('td:nth-child(4)').appendChild(sourceBadge);
            }
            tbody.appendChild(tr);
          });
        } else if (activeTab === 'altium') {
          document.getElementById('singleViewTitle').textContent = I18N.tab_altium || 'Altium Libraries';
          thead.innerHTML = `
            <tr>
              <th style="min-width: 160px;">${I18N.th_specs || 'Specs'}</th>
              <th style="width: 110px;">${I18N.th_package || 'Package'}</th>
              <th>${I18N.th_lib_ref || 'Library Ref'}</th>
              <th style="min-width: 130px;">${I18N.th_category || 'Category'}</th>
              <th style="min-width: 120px;">${I18N.th_manufacturer || 'Manufacturer'}</th>
              <th style="width: 110px;">${I18N.th_lcsc_part || 'LCSC Part'}</th>
              <th style="width: 150px;" class="text-end">${I18N.th_actions || 'Actions'}</th>
            </tr>
          `;
          data.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td><strong class="text-dark">${escapeHtml(formatAltiumSpecs(item))}</strong></td>
              <td><code>${escapeHtml(item.package || '-')}</code></td>
              <td>
                <a href="/libraries/altium/${item.id}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.lib_reference || '-')}</a>
              </td>
              <td><small class="text-secondary">${escapeHtml(item.category_localized || item.category || '-')}</small></td>
              <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.lcsc_part || '-')}</span></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('altium', '${item.id}', '${escapeHtml(item.lib_reference || '')}', '${escapeHtml(item.package || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/altium/${item.id}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            tbody.appendChild(tr);
          });
        } else if (activeTab === 'kicad') {
          document.getElementById('singleViewTitle').textContent = I18N.tab_kicad || 'KiCad Symbols';
          thead.innerHTML = `
            <tr>
              <th>${I18N.th_name || 'Symbol'}</th>
              <th style="width: 180px;">${I18N.th_library || 'Library'}</th>
              <th style="width: 200px;">${I18N.th_footprint || 'Footprint'}</th>
              <th style="width: 160px;" class="text-end">${I18N.th_actions || 'Actions'}</th>
            </tr>
          `;
          data.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td>
                <a href="/libraries/kicad/${item.id}" class="fw-bold text-decoration-none text-primary d-block">${escapeHtml(item.name || item.value || '-')}</a>
                <small class="text-muted">${escapeHtml(item.description || '')}</small>
              </td>
              <td><span class="badge bg-secondary">${escapeHtml(item.library || '-')}</span></td>
              <td><code>${escapeHtml(item.footprint || '-')}</code></td>
              <td class="text-end">
                <div class="d-inline-flex gap-1">
                  <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('kicad', '${item.id}', '${escapeHtml(item.name || '')}', '${escapeHtml(item.library || '')}')">
                    + Add
                  </button>
                  <a href="/libraries/kicad/${item.id}" class="btn btn-outline-primary btn-sm">Details</a>
                </div>
              </td>
            `;
            tbody.appendChild(tr);
          });
        } else if (activeTab === 'fasteners') {
          document.getElementById('singleViewTitle').textContent = I18N.tab_fasteners || 'Fasteners Library';
          thead.innerHTML = `
            <tr>
              <th style="min-width: 140px;">${I18N.th_code || 'Standard Code'}</th>
              <th style="min-width: 100px;">${I18N.th_authority || 'Authority'}</th>
              <th style="min-width: 140px;">${I18N.th_category || 'Category'}</th>
              <th>${I18N.th_description || 'Description'}</th>
              <th style="width: 110px;" class="text-center">${I18N.th_has_length || 'Length'}</th>
              <th style="width: 140px;" class="text-end">${I18N.th_actions || 'Actions'}</th>
            </tr>
          `;
          data.items.forEach(item => {
            const tr = document.createElement('tr');
            const lengthBadge = item.has_length
              ? '<span class="badge bg-success-subtle text-success border border-success-subtle">多长度系列</span>'
              : '<span class="badge bg-light text-muted border">单件/无长度</span>';
            tr.innerHTML = `
              <td>
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="fw-bold text-decoration-none text-primary">
                  ${escapeHtml(item.standard_code)}
                </a>
              </td>
              <td><span class="badge bg-secondary">${escapeHtml(item.authority || 'STD')}</span></td>
              <td><span class="badge bg-light text-dark border">${escapeHtml(item.category_group_zh || item.category_group || '-')}</span></td>
              <td>
                <div class="text-dark">${escapeHtml(item.description || item.standard_name || '-')}</div>
                <small class="text-muted">${escapeHtml(item.param_table_name || '')}</small>
              </td>
              <td class="text-center">${lengthBadge}</td>
              <td class="text-end">
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="btn btn-outline-primary btn-sm">详情</a>
              </td>
            `;
            tbody.appendChild(tr);
          });
        }

        renderPagination(data);
      }

      function renderPagination(data) {
        const page = data.page || 1;
        const totalPages = data.total_pages || 1;
        const total = data.total || 0;
        const nav = document.getElementById('paginationNav');
        nav.innerHTML = '';

        document.getElementById('paginationInfo').textContent = `Page ${page} of ${totalPages} (${total.toLocaleString()} total items)`;

        if (totalPages <= 1) return;

        // Prev
        const prevLi = document.createElement('li');
        prevLi.className = `page-item ${page <= 1 ? 'disabled' : ''}`;
        prevLi.innerHTML = `<a class="page-link" href="#">&laquo;</a>`;
        if (page > 1) {
          prevLi.querySelector('a').addEventListener('click', (e) => {
            e.preventDefault();
            currentPage = page - 1;
            executeSearch();
          });
        }
        nav.appendChild(prevLi);

        // Visible page numbers window
        let startPage = Math.max(1, page - 2);
        let endPage = Math.min(totalPages, page + 2);
        if (page <= 3) endPage = Math.min(totalPages, 5);
        if (page >= totalPages - 2) startPage = Math.max(1, totalPages - 4);

        for (let p = startPage; p <= endPage; p++) {
          const li = document.createElement('li');
          li.className = `page-item ${p === page ? 'active' : ''}`;
          li.innerHTML = `<a class="page-link" href="#">${p}</a>`;
          const targetPage = p;
          li.querySelector('a').addEventListener('click', (e) => {
            e.preventDefault();
            currentPage = targetPage;
            executeSearch();
          });
          nav.appendChild(li);
        }

        // Next
        const nextLi = document.createElement('li');
        nextLi.className = `page-item ${page >= totalPages ? 'disabled' : ''}`;
        nextLi.innerHTML = `<a class="page-link" href="#">&raquo;</a>`;
        if (page < totalPages) {
          nextLi.querySelector('a').addEventListener('click', (e) => {
            e.preventDefault();
            currentPage = page + 1;
            executeSearch();
          });
        }
        nav.appendChild(nextLi);
      }

      // Tab switcher
      document.querySelectorAll('#searchTabs .nav-link').forEach(btn => {
        btn.addEventListener('click', function() {
          document.querySelectorAll('#searchTabs .nav-link').forEach(b => b.classList.remove('active'));
          this.classList.add('active');
          activeTab = this.getAttribute('data-tab');
          currentPage = 1;
          executeSearch();
        });
      });

      // Overview "View All" links
      document.addEventListener('click', function(e) {
        const link = e.target.closest('.switch-tab-link');
        if (link) {
          e.preventDefault();
          const target = link.getAttribute('data-target');
          const targetTabBtn = document.querySelector(`#searchTabs button[data-tab="${target}"]`);
          if (targetTabBtn) {
            targetTabBtn.click();
          }
        }
      });

      // Clear button
      document.getElementById('centerClearBtn').addEventListener('click', function() {
        document.getElementById('centerSearchInput').value = '';
        executeSearch();
      });

      // Form submission
      document.getElementById('globalSearchForm').addEventListener('submit', function(e) {
        e.preventDefault();
        currentPage = 1;
        executeSearch();
      });

      // Page size change
      document.getElementById('pageSizeSelect').addEventListener('change', function() {
        currentPageSize = parseInt(this.value, 10);
        currentPage = 1;
        executeSearch();
      });

      // Initial load
      document.addEventListener('DOMContentLoaded', () => {
        const urlParams = new URLSearchParams(window.location.search);
        const qParam = urlParams.get('q');
        const tabParam = urlParams.get('tab');
        const pageParam = urlParams.get('page');

        if (qParam) {
          currentQuery = qParam;
          document.getElementById('centerSearchInput').value = qParam;
        }
        if (tabParam && ['all', 'inventory', 'jlcparts', 'altium', 'kicad'].includes(tabParam)) {
          activeTab = tabParam;
          document.querySelectorAll('#searchTabs .nav-link').forEach(b => b.classList.remove('active'));
          const activeBtn = document.querySelector(`#searchTabs button[data-tab="${tabParam}"]`);
          if (activeBtn) activeBtn.classList.add('active');
        }
        if (pageParam && parseInt(pageParam, 10) > 0) {
          currentPage = parseInt(pageParam, 10);
        }

        if (currentQuery) {
          executeSearch();
        }
      });
