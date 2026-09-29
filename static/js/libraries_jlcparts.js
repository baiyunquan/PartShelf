const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let currentPage = 1;
      let categoriesTree = [];

      async function loadCategories() {
        try {
          const res = await fetch('/api/libraries/jlcparts/categories');
          categoriesTree = await res.json();
          const select = document.getElementById('categoryFilter');
          categoriesTree.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.category;
            opt.textContent = c.category_localized || c.category;
            select.appendChild(opt);
          });
        } catch (e) {
          console.error('Failed to load categories', e);
        }
      }

      function updateSubcategories(chosenCategory) {
        const subSelect = document.getElementById('subcategoryFilter');
        subSelect.innerHTML = `<option value="">${i18n.filter_subcategory || 'All Subcategories'}</option>`;
        if (!chosenCategory) {
          subSelect.disabled = true;
          return;
        }
        const item = categoriesTree.find(c => c.category === chosenCategory);
        if (item && item.subcategories && item.subcategories.length > 0) {
          item.subcategories.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.subcategory;
            const subText = s.subcategory_localized || s.subcategory;
            opt.textContent = `${subText} (${s.count})`;
            subSelect.appendChild(opt);
          });
          subSelect.disabled = false;
        } else {
          subSelect.disabled = true;
        }
      }

      async function fetchParts(page = 1) {
        currentPage = page;
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = `<tr><td colspan="10" class="text-center py-5 text-muted">${i18n.loading || 'Loading...'}</td></tr>`;

        const q = document.getElementById('searchInput').value.trim();
        const cat = document.getElementById('categoryFilter').value;
        const subcat = document.getElementById('subcategoryFilter').value;
        const libType = document.getElementById('libraryTypeFilter').value;
        const inStock = document.getElementById('inStockCheck').checked;
        const pageSize = document.getElementById('pageSizeSelect').value;

        const params = new URLSearchParams({
          q: q,
          page: page,
          page_size: pageSize
        });
        if (cat) params.append('category', cat);
        if (subcat) params.append('subcategory', subcat);
        if (libType) params.append('library_type', libType);
        if (inStock) params.append('in_stock_only', 'true');

        try {
          const res = await fetch(`/api/libraries/jlcparts?${params.toString()}`);
          const data = await res.json();
          renderTable(data);
        } catch (e) {
          tbody.innerHTML = `<tr><td colspan="10" class="text-center py-5 text-danger">Error loading data</td></tr>`;
        }
      }

      function renderTable(data) {
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = '';

        document.getElementById('totalCountBadge').textContent = (data.total || 0).toLocaleString();

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="10" class="text-center py-5 text-muted">${i18n.no_data || 'No records found'}</td></tr>`;
          document.getElementById('paginationInfo').textContent = '';
          document.getElementById('paginationNav').innerHTML = '';
          return;
        }

        data.items.forEach(item => {
          const tr = document.createElement('tr');
          const isBasic = item.library_type === 'base';
          const typeBadge = isBasic ?
            `<span class="badge bg-success">${i18n.badge_basic || 'Basic'}</span>` :
            `<span class="badge bg-light text-dark border">${i18n.badge_extended || 'Expand'}</span>`;

          const stockClass = item.stock > 0 ? 'text-success fw-bold' : 'text-muted';
          const stockText = item.stock > 0 ? item.stock.toLocaleString() : '0';

          let priceText = '-';
          if (item.price_breaks && item.price_breaks.length > 0) {
            priceText = `$${item.price_breaks[0].price}`;
          }

          let imgHtml = '<div class="bg-light rounded d-flex align-items-center justify-content-center text-muted border" style="width: 44px; height: 44px; font-size: 0.65rem;">IC</div>';
          if (item.image_url_small) {
            imgHtml = `<img src="${item.image_url_small}" alt="Part" class="rounded border" style="width: 44px; height: 44px; object-fit: contain; background: #fff;" loading="lazy" onerror="this.outerHTML='<div class=\\'bg-light rounded d-flex align-items-center justify-content-center text-muted border\\' style=\\'width: 44px; height: 44px; font-size: 0.65rem;\\'>IC</div>'">`;
          }

          tr.innerHTML = `
            <td class="text-center">${imgHtml}</td>
            <td><strong class="text-dark">${escapeHtml(item.specs || '-')}</strong></td>
            <td><code>${escapeHtml(item.package || '-')}</code></td>
            <td>
              <a href="/libraries/jlcparts/${item.lcsc}" class="fw-bold text-decoration-none text-primary d-block">
                ${escapeHtml(item.mfr || '-')}
              </a>
              <div class="d-flex gap-1 mt-1">${typeBadge}</div>
            </td>
            <td>
              <small class="d-block fw-bold text-dark" title="${escapeHtml(item.category || '')}">${escapeHtml(item.category_localized || item.category || '-')}</small>
              <small class="text-secondary" title="${escapeHtml(item.subcategory || '')}">${escapeHtml(item.subcategory_localized || item.subcategory || '-')}</small>
            </td>
            <td><small class="text-muted">${escapeHtml(item.manufacturer || '-')}</small></td>
            <td>
              <a href="/libraries/jlcparts/${item.lcsc}" class="badge bg-light text-dark border text-decoration-none fw-bold">
                C${item.lcsc}
              </a>
            </td>
            <td><span class="${stockClass}">${stockText}</span></td>
            <td><small class="text-dark fw-bold">${priceText}</small></td>
            <td class="text-end">
              <div class="d-inline-flex gap-1">
                <button class="btn btn-outline-success btn-sm text-nowrap" onclick="openImportModal('jlcparts', '${item.lcsc}', 'C${item.lcsc} (${escapeHtml(item.mfr || '')})', '${escapeHtml(item.package || '')} | ${escapeHtml(item.category || '')}')">
                  ${i18n.btn_quick_add || '+ Add'}
                </button>
                <a href="/libraries/jlcparts/${item.lcsc}" class="btn btn-outline-primary btn-sm text-nowrap">
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

      document.getElementById('categoryFilter').addEventListener('change', (e) => {
        updateSubcategories(e.target.value);
        fetchParts(1);
      });
      document.getElementById('subcategoryFilter').addEventListener('change', () => fetchParts(1));
      document.getElementById('libraryTypeFilter').addEventListener('change', () => fetchParts(1));
      document.getElementById('inStockCheck').addEventListener('change', () => fetchParts(1));
      document.getElementById('pageSizeSelect').addEventListener('change', () => fetchParts(1));

      document.getElementById('resetBtn').addEventListener('click', () => {
        document.getElementById('searchInput').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('subcategoryFilter').value = '';
        document.getElementById('subcategoryFilter').disabled = true;
        document.getElementById('libraryTypeFilter').value = '';
        document.getElementById('inStockCheck').checked = false;
        fetchParts(1);
      });

      // Init
      loadCategories();
      fetchParts(1);
