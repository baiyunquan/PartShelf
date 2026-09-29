const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let currentPage = 1;

      async function loadLibraries() {
        try {
          const res = await fetch('/api/libraries/kicad/libraries');
          const libs = await res.json();
          const select = document.getElementById('libraryFilter');
          libs.forEach(l => {
            const opt = document.createElement('option');
            opt.value = l;
            opt.textContent = l;
            select.appendChild(opt);
          });
        } catch (e) {
          console.error('Failed to load libraries', e);
        }
      }

      async function fetchSymbols(page = 1) {
        currentPage = page;
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = `<tr><td colspan="7" class="text-center py-5 text-muted">${i18n.loading || 'Loading...'}</td></tr>`;

        const q = document.getElementById('searchInput').value.trim();
        const lib = document.getElementById('libraryFilter').value;
        const pageSize = document.getElementById('pageSizeSelect').value;

        const params = new URLSearchParams({
          q: q,
          page: page,
          page_size: pageSize
        });
        if (lib) params.append('library', lib);

        try {
          const res = await fetch(`/api/libraries/kicad?${params.toString()}`);
          const data = await res.json();
          renderTable(data);
        } catch (e) {
          tbody.innerHTML = `<tr><td colspan="7" class="text-center py-5 text-danger">Error loading data</td></tr>`;
        }
      }

      function renderTable(data) {
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = '';

        document.getElementById('totalCountBadge').textContent = (data.total || 0).toLocaleString();

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" class="text-center py-5 text-muted">${i18n.no_data || 'No records found'}</td></tr>`;
          document.getElementById('paginationInfo').textContent = '';
          document.getElementById('paginationNav').innerHTML = '';
          return;
        }

        data.items.forEach(item => {
          const tr = document.createElement('tr');
          const descText = item.description || (item.keywords ? `Keywords: ${item.keywords}` : '-');

          tr.innerHTML = `
            <td>
              <a href="/libraries/kicad/${item.id}" class="fw-bold text-decoration-none text-primary">
                ${escapeHtml(item.name)}
              </a>
            </td>
            <td><span class="badge bg-secondary">${escapeHtml(item.library)}</span></td>
            <td><code>${escapeHtml(item.reference || '-')}</code></td>
            <td><small class="text-muted">${escapeHtml(item.extends || '-')}</small></td>
            <td><small class="text-dark"><code>${escapeHtml(item.footprint || '-')}</code></small></td>
            <td><small class="text-secondary">${escapeHtml(descText)}</small></td>
            <td class="text-end">
              <div class="d-inline-flex gap-1">
                <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('kicad', '${item.id}', '${escapeHtml(item.name)}', '${escapeHtml(item.footprint || '')} | ${escapeHtml(item.library || '')}')">
                  ${i18n.btn_quick_add || '+ Add'}
                </button>
                <a href="/libraries/kicad/${item.id}" class="btn btn-outline-primary btn-sm text-nowrap">
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
              fetchSymbols(pageNum);
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
        fetchSymbols(1);
      });

      document.getElementById('libraryFilter').addEventListener('change', () => fetchSymbols(1));
      document.getElementById('pageSizeSelect').addEventListener('change', () => fetchSymbols(1));

      document.getElementById('resetBtn').addEventListener('click', () => {
        document.getElementById('searchInput').value = '';
        document.getElementById('libraryFilter').value = '';
        fetchSymbols(1);
      });

      // Init
      loadLibraries();
      fetchSymbols(1);
