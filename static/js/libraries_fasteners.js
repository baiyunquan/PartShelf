const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let currentPage = 1;
      let currentDomain = '';

      const DOMAIN_LABELS = {
        'fasteners': i18n['libraries_fasteners.domain_fasteners'] || '紧固件',
        'power_transmission': i18n['libraries_fasteners.domain_power_transmission'] || '动力传动',
        'structural_materials': i18n['libraries_fasteners.domain_structural_materials'] || '结构材料 / 型材'
      };

      const DOMAIN_BADGES = {
        'fasteners': 'badge bg-secondary',
        'power_transmission': 'badge bg-info-subtle text-info-emphasis border border-info-subtle',
        'structural_materials': 'badge bg-warning-subtle text-warning-emphasis border border-warning-subtle'
      };

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      async function loadDomains() {
        try {
          const res = await fetch('/api/libraries/fasteners/domains');
          if (res.ok) {
            const domains = await res.json();
            let total = 0;
            domains.forEach(d => {
              total += (d.count || 0);
              if (d.domain === 'fasteners') {
                const el = document.getElementById('domainCountFasteners');
                if (el) el.textContent = d.count.toLocaleString();
              } else if (d.domain === 'power_transmission') {
                const el = document.getElementById('domainCountPowerTransmission');
                if (el) el.textContent = d.count.toLocaleString();
              } else if (d.domain === 'structural_materials') {
                const el = document.getElementById('domainCountStructuralMaterials');
                if (el) el.textContent = d.count.toLocaleString();
              }
            });
            const allEl = document.getElementById('domainCountAll');
            if (allEl) allEl.textContent = total.toLocaleString();
          }
        } catch (err) {
          console.error('Error loading domains:', err);
        }
      }

      async function loadCategories(domain = '') {
        try {
          const url = domain ? `/api/libraries/fasteners/categories?domain=${encodeURIComponent(domain)}` : '/api/libraries/fasteners/categories';
          const res = await fetch(url);
          if (res.ok) {
            const categories = await res.json();
            const catSelect = document.getElementById('categoryFilter');
            catSelect.innerHTML = `<option value="">${i18n['libraries_fasteners.filter_all_categories'] || '全部分类'}</option>`;
            categories.forEach(c => {
              const opt = document.createElement('option');
              opt.value = c.group;
              opt.textContent = `${c.group_zh || c.group} (${c.count})`;
              catSelect.appendChild(opt);
            });
          }
        } catch (err) {
          console.error('Error loading categories:', err);
        }
      }

      async function loadAuthorities() {
        try {
          const res = await fetch('/api/libraries/fasteners/authorities');
          if (res.ok) {
            const authorities = await res.json();
            const authSelect = document.getElementById('authorityFilter');
            authSelect.innerHTML = `<option value="">${i18n['libraries_fasteners.filter_all_authorities'] || '全部体系'}</option>`;
            authorities.forEach(a => {
              const opt = document.createElement('option');
              opt.value = a.authority;
              opt.textContent = `${a.authority} (${a.count})`;
              authSelect.appendChild(opt);
            });
          }
        } catch (err) {
          console.error('Error loading authorities:', err);
        }
      }

      async function fetchFasteners(page = 1) {
        currentPage = page;
        const q = document.getElementById('searchInput').value.trim();
        const cat = document.getElementById('categoryFilter').value;
        const auth = document.getElementById('authorityFilter').value;
        const pageSize = document.getElementById('pageSizeSelect').value;

        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = `<tr><td colspan="7" class="text-center py-5 text-muted">${i18n['libraries_common.loading'] || 'Loading data...'}</td></tr>`;

        const params = new URLSearchParams({
          page: page,
          page_size: pageSize
        });
        if (q) params.set('q', q);
        if (cat) params.set('category', cat);
        if (auth) params.set('authority', auth);
        if (currentDomain) params.set('domain', currentDomain);

        try {
          const res = await fetch(`/api/libraries/fasteners?${params.toString()}`);
          if (!res.ok) throw new Error('Network error');
          const data = await res.json();
          renderTable(data);
          renderPagination(data);
        } catch (err) {
          tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-danger">Error loading mechanical records: ${escapeHtml(err.message)}</td></tr>`;
        }
      }

      function renderTable(data) {
        const tbody = document.getElementById('tableBody');
        const badge = document.getElementById('totalCountBadge');
        if (badge) badge.textContent = (data.total || 0).toLocaleString();

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" class="text-center py-5 text-muted">${i18n['libraries_common.no_data'] || 'No records found'}</td></tr>`;
          return;
        }

        let html = '';
        data.items.forEach(item => {
          const authBadge = `<span class="badge bg-secondary">${escapeHtml(item.authority || 'STD')}</span>`;
          const domName = DOMAIN_LABELS[item.domain] || item.domain || '-';
          const domClass = DOMAIN_BADGES[item.domain] || 'badge bg-light text-dark border';
          const domBadge = `<span class="${domClass}">${escapeHtml(domName)}</span>`;
          const catName = escapeHtml(item.category_group_zh || item.category_group || '-');
          const catBadge = `<span class="badge bg-light text-dark border">${catName}</span>`;
          const lengthBadge = item.has_length
            ? '<span class="badge bg-success-subtle text-success border border-success-subtle">多长度系列</span>'
            : '<span class="badge bg-light text-muted border">单件/无长度</span>';

          html += `
            <tr>
              <td>
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="fw-bold text-decoration-none text-primary">
                  ${escapeHtml(item.standard_code)}
                </a>
              </td>
              <td>${authBadge}</td>
              <td>${domBadge}</td>
              <td>${catBadge}</td>
              <td>
                <div class="text-dark">${escapeHtml(item.description || item.standard_name || '-')}</div>
                <small class="text-muted">${escapeHtml(item.param_table_name || '')}</small>
              </td>
              <td class="text-center">${lengthBadge}</td>
              <td class="text-end">
                <a href="/libraries/fasteners/${encodeURIComponent(item.standard_code)}" class="btn btn-sm btn-outline-primary">
                  ${i18n['libraries_common.view_details'] || '查看详情'}
                </a>
              </td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      }

      function renderPagination(data) {
        const info = document.getElementById('paginationInfo');
        const nav = document.getElementById('paginationNav');
        const total = data.total || 0;
        const page = data.page || 1;
        const totalPages = data.total_pages || 1;

        let infoText = (i18n['libraries_common.pagination_info'] || 'Total {total} records, page {page} of {total_pages}')
          .replace('{total}', total.toLocaleString())
          .replace('{page}', page)
          .replace('{total_pages}', totalPages);
        info.textContent = infoText;

        let navHtml = '';
        navHtml += `
          <li class="page-item ${page <= 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="fetchFasteners(${page - 1}); return false;">${i18n['libraries_common.prev_page'] || 'Previous'}</a>
          </li>
        `;

        const startPage = Math.max(1, page - 2);
        const endPage = Math.min(totalPages, page + 2);
        for (let p = startPage; p <= endPage; p++) {
          navHtml += `
            <li class="page-item ${p === page ? 'active' : ''}">
              <a class="page-link" href="#" onclick="fetchFasteners(${p}); return false;">${p}</a>
            </li>
          `;
        }

        navHtml += `
          <li class="page-item ${page >= totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="fetchFasteners(${page + 1}); return false;">${i18n['libraries_common.next_page'] || 'Next'}</a>
          </li>
        `;
        nav.innerHTML = navHtml;
      }

      function setupDomainButtons() {
        document.querySelectorAll('.domain-btn').forEach(btn => {
          btn.addEventListener('click', function() {
            document.querySelectorAll('.domain-btn').forEach(b => {
              b.classList.remove('active', 'fw-bold');
              const badge = b.querySelector('.badge');
              if (badge) {
                badge.classList.remove('bg-primary');
                badge.classList.add('bg-secondary');
              }
            });
            this.classList.add('active', 'fw-bold');
            const badge = this.querySelector('.badge');
            if (badge) {
              badge.classList.remove('bg-secondary');
              badge.classList.add('bg-primary');
            }

            currentDomain = this.getAttribute('data-domain') || '';
            document.getElementById('categoryFilter').value = '';
            loadCategories(currentDomain);
            fetchFasteners(1);
          });
        });
      }

      document.getElementById('filterForm').addEventListener('submit', function(e) {
        e.preventDefault();
        fetchFasteners(1);
      });

      document.getElementById('categoryFilter').addEventListener('change', () => fetchFasteners(1));
      document.getElementById('authorityFilter').addEventListener('change', () => fetchFasteners(1));
      document.getElementById('pageSizeSelect').addEventListener('change', () => fetchFasteners(1));

      document.getElementById('resetBtn').addEventListener('click', function() {
        document.getElementById('searchInput').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('authorityFilter').value = '';
        document.getElementById('pageSizeSelect').value = '25';
        currentDomain = '';
        document.querySelectorAll('.domain-btn').forEach(b => {
          b.classList.remove('active', 'fw-bold');
          const badge = b.querySelector('.badge');
          if (badge) {
            badge.classList.remove('bg-primary');
            badge.classList.add('bg-secondary');
          }
        });
        const firstBtn = document.querySelector('.domain-btn[data-domain=""]');
        if (firstBtn) {
          firstBtn.classList.add('active', 'fw-bold');
          const badge = firstBtn.querySelector('.badge');
          if (badge) {
            badge.classList.remove('bg-secondary');
            badge.classList.add('bg-primary');
          }
        }
        loadCategories('');
        fetchFasteners(1);
      });

      document.addEventListener('DOMContentLoaded', () => {
        setupDomainButtons();
        loadDomains();
        loadCategories('');
        loadAuthorities();
        fetchFasteners(1);
      });
