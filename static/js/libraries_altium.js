const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let currentPage = 1;

      async function loadCategories() {
        try {
          const res = await fetch('/api/libraries/altium/categories');
          const cats = await res.json();
          const select = document.getElementById('categoryFilter');
          cats.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.category;
            opt.textContent = c.category_localized || c.category;
            select.appendChild(opt);
          });
        } catch (e) {
          console.error('Failed to load categories', e);
        }
      }

      function formatSpecs(item) {
        const parts = [];
        if (item.resistance) parts.push(item.resistance);
        if (item.capacitance) parts.push(item.capacitance);
        if (item.inductance) parts.push(item.inductance);
        if (item.tolerance) parts.push(item.tolerance);
        if (item.voltage_rating) parts.push(item.voltage_rating);
        if (item.power_rating) parts.push(item.power_rating);
        if (parts.length > 0) return parts.join(', ');
        return item.description ? (item.description.length > 40 ? item.description.substring(0, 38) + '...' : item.description) : '-';
      }

      async function fetchParts(page = 1) {
        currentPage = page;
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-5 text-muted">${i18n.loading || 'Loading...'}</td></tr>`;

        const q = document.getElementById('searchInput').value.trim();
        const cat = document.getElementById('categoryFilter').value;
        const basic = document.getElementById('basicFilter').value;
        const pageSize = document.getElementById('pageSizeSelect').value;

        const params = new URLSearchParams({
          q: q,
          page: page,
          page_size: pageSize
        });
        if (cat) params.append('category', cat);
        if (basic !== '') params.append('basic_only', basic === '1');

        try {
          const res = await fetch(`/api/libraries/altium?${params.toString()}`);
          const data = await res.json();
          renderTable(data);
        } catch (e) {
          tbody.innerHTML = `<tr><td colspan="8" class="text-center py-5 text-danger">Error loading data</td></tr>`;
        }
      }

      function renderTable(data) {
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = '';

        document.getElementById('totalCountBadge').textContent = (data.total || 0).toLocaleString();

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="text-center py-5 text-muted">${i18n.no_data || 'No records found'}</td></tr>`;
          document.getElementById('paginationInfo').textContent = '';
          document.getElementById('paginationNav').innerHTML = '';
          return;
        }

        data.items.forEach(item => {
          const tr = document.createElement('tr');
          const isBasic = item.basic_part === 1;
          const badgeClass = isBasic ? 'bg-success' : 'bg-secondary';
          const badgeText = isBasic ? (i18n.badge_basic || 'Basic') : (i18n.badge_extended || 'Extended');

          tr.innerHTML = `
            <td><strong class="text-dark">${escapeHtml(formatSpecs(item))}</strong></td>
            <td><code>${escapeHtml(item.package || '-')}</code></td>
            <td>
              <a href="/libraries/altium/${item.id}" class="fw-bold text-decoration-none text-primary">
                ${escapeHtml(item.lib_reference || '-')}
              </a>
            </td>
            <td><small class="text-secondary" title="${escapeHtml(item.category || '')}">${escapeHtml(item.category_localized || item.category || '-')}</small></td>
            <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
            <td>
              ${item.lcsc_part ? `<span class="badge bg-light text-dark border">${escapeHtml(item.lcsc_part)}</span>` : '-'}
            </td>
            <td><span class="badge ${badgeClass}">${badgeText}</span></td>
            <td class="text-end">
              <div class="d-inline-flex gap-1">
                <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('altium', '${item.id}', '${escapeHtml(item.lib_reference)}', '${escapeHtml(item.package || '')} | ${escapeHtml(item.manufacturer || '')}')">
                  ${i18n.btn_quick_add || '+ Add'}
                </button>
                <a href="/libraries/altium/${item.id}" class="btn btn-outline-primary btn-sm text-nowrap">
                  ${i18n.view_details || 'Details'}
                </a>
              </div>
            </td>
          `;
          tbody.appendChild(tr);
        });

        renderPagination(data);
      }

      function renderPagination(data) {
        const infoEl = document.getElementById('paginationInfo');
        const navEl = document.getElementById('paginationNav');
        navEl.innerHTML = '';

        const template = i18n.pagination_info || 'Total {total}, page {page} of {total_pages}';
        infoEl.textContent = template
          .replace('{total}', (data.total || 0).toLocaleString())
          .replace('{page}', data.page)
          .replace('{total_pages}', data.total_pages);

        if (data.total_pages <= 1) return;

        const createPageItem = (pageNum, text, isActive = false, isDisabled = false) => {
          const li = document.createElement('li');
          li.className = `page-item ${isActive ? 'active' : ''} ${isDisabled ? 'disabled' : ''}`;
          const a = document.createElement('a');
          a.className = 'page-link';
          a.href = '#';
          a.textContent = text;
          if (!isDisabled && !isActive) {
            a.onclick = (e) => {
              e.preventDefault();
              fetchParts(pageNum);
            };
          }
          li.appendChild(a);
          return li;
        };

        navEl.appendChild(createPageItem(data.page - 1, i18n.prev_page || 'Prev', false, data.page <= 1));

        const startPage = Math.max(1, data.page - 2);
        const endPage = Math.min(data.total_pages, data.page + 2);

        if (startPage > 1) {
          navEl.appendChild(createPageItem(1, '1'));
          if (startPage > 2) {
            const ellipsis = document.createElement('li');
            ellipsis.className = 'page-item disabled';
            ellipsis.innerHTML = '<span class="page-link">...</span>';
            navEl.appendChild(ellipsis);
          }
        }

        for (let p = startPage; p <= endPage; p++) {
          navEl.appendChild(createPageItem(p, p.toString(), p === data.page));
        }

        if (endPage < data.total_pages) {
          if (endPage < data.total_pages - 1) {
            const ellipsis = document.createElement('li');
            ellipsis.className = 'page-item disabled';
            ellipsis.innerHTML = '<span class="page-link">...</span>';
            navEl.appendChild(ellipsis);
          }
          navEl.appendChild(createPageItem(data.total_pages, data.total_pages.toString()));
        }

        navEl.appendChild(createPageItem(data.page + 1, i18n.next_page || 'Next', false, data.page >= data.total_pages));
      }

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      document.getElementById('filterForm').addEventListener('submit', (e) => {
        e.preventDefault();
        fetchParts(1);
      });

      document.getElementById('categoryFilter').addEventListener('change', () => fetchParts(1));
      document.getElementById('basicFilter').addEventListener('change', () => fetchParts(1));
      document.getElementById('pageSizeSelect').addEventListener('change', () => fetchParts(1));

      document.getElementById('resetBtn').addEventListener('click', () => {
        document.getElementById('searchInput').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('basicFilter').value = '';
        fetchParts(1);
      });

      // Init
      loadCategories();
      fetchParts(1);
