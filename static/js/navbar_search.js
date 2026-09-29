(() => {
  const navI18n = JSON.parse(document.getElementById('navbar-translations')?.textContent || '{}');

  const searchInput = document.getElementById('topNavbarSearchInput');
  const dropdown = document.getElementById('navbarLiveDropdown');
  const searchForm = document.getElementById('navbarSearchForm');
  let debounceTimer = null;

  if (!searchInput || !dropdown) return;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[m]);
  }

  async function fetchQuickSearch(query) {
    if (!query) {
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
      return;
    }

    try {
      const res = await fetch(`/api/search/quick?q=${encodeURIComponent(query)}`);
      if (!res.ok) return;
      const data = await res.json();
      renderDropdown(data, query);
    } catch (e) {
      console.error('Quick search error', e);
    }
  }

  function renderDropdown(data, query) {
    dropdown.innerHTML = '';
    const total = data.total_matches || 0;

    if (total === 0) {
      dropdown.innerHTML = `
        <div class="p-3 text-center text-muted small">
          ${navI18n.live_no_matches || 'No matches found'}
        </div>
      `;
      dropdown.style.display = 'block';
      return;
    }

    let html = '';

    // 1. Inventory Matches
    if (data.inventory && data.inventory.items && data.inventory.items.length > 0) {
      html += `
        <div class="px-3 py-1 bg-light text-uppercase fw-bold text-secondary border-bottom" style="font-size: 0.72rem; letter-spacing: 0.5px;">
          ${navI18n.card_inventory_title || 'Inventory'} (${data.inventory.total})
        </div>
      `;
      data.inventory.items.forEach(item => {
        html += `
          <a href="${item.url}" class="dropdown-item py-2 px-3 border-bottom d-flex justify-content-between align-items-center">
            <div class="text-truncate me-2">
              <span class="badge bg-light text-dark border me-1">#${item.id}</span>
              <strong class="text-primary">${escapeHtml(item.name)}</strong>
              <small class="text-muted d-block text-truncate">${escapeHtml(item.package || '-')} | ${escapeHtml(item.storage_location || 'Default Storage')}</small>
            </div>
            <span class="badge ${item.quantity > 0 ? 'bg-success' : 'bg-danger'}">${item.quantity}</span>
          </a>
        `;
      });
    }

    // 2. JLCParts Matches
    if (data.jlcparts && data.jlcparts.items && data.jlcparts.items.length > 0) {
      html += `
        <div class="px-3 py-1 bg-light text-uppercase fw-bold text-secondary border-bottom" style="font-size: 0.72rem; letter-spacing: 0.5px;">
          ${navI18n.card_jlcparts_title || 'JLCParts'} (${data.jlcparts.total})
        </div>
      `;
      data.jlcparts.items.forEach(item => {
        let imgTag = '<div class="bg-light rounded d-inline-flex align-items-center justify-content-center text-muted border me-2" style="width: 28px; height: 28px; font-size: 0.55rem;">IC</div>';
        if (item.image) {
          imgTag = `<img src="${item.image}" class="rounded border me-2" style="width: 28px; height: 28px; object-fit: contain; background: #fff;" onerror="this.outerHTML='<div class=\\'bg-light rounded d-inline-flex align-items-center justify-content-center text-muted border me-2\\' style=\\'width: 28px; height: 28px; font-size: 0.55rem;\\'>IC</div>'">`;
        }
        const priceTag = item.price ? `<span class="badge bg-light text-dark border ms-1">$${item.price}</span>` : '';
        html += `
          <a href="${item.url}" class="dropdown-item py-2 px-3 border-bottom d-flex justify-content-between align-items-center">
            <div class="d-flex align-items-center text-truncate me-2">
              ${imgTag}
              <div class="text-truncate">
                <span class="badge bg-light text-dark border me-1">C${item.lcsc}</span>
                <strong class="text-dark">${escapeHtml(item.mfr)}</strong>
                <small class="text-muted d-block text-truncate">${escapeHtml(item.package || '-')}</small>
              </div>
            </div>
            <div class="text-end text-nowrap">
              <span class="badge ${item.stock > 0 ? 'bg-success' : 'bg-secondary'}">${item.stock > 0 ? item.stock.toLocaleString() : '0'}</span>
              ${priceTag}
            </div>
          </a>
        `;
      });
    }

    // 3. Altium Matches
    if (data.altium && data.altium.items && data.altium.items.length > 0) {
      html += `
        <div class="px-3 py-1 bg-light text-uppercase fw-bold text-secondary border-bottom" style="font-size: 0.72rem; letter-spacing: 0.5px;">
          ${navI18n.card_altium_title || 'Altium'} (${data.altium.total})
        </div>
      `;
      data.altium.items.forEach(item => {
        const lcscBadge = item.lcsc_part ? `<span class="badge bg-light text-dark border ms-1">${escapeHtml(item.lcsc_part)}</span>` : '';
        html += `
          <a href="${item.url}" class="dropdown-item py-2 px-3 border-bottom d-flex justify-content-between align-items-center">
            <div class="text-truncate me-2">
              <span class="badge bg-dark me-1">Altium</span>
              <strong class="text-dark">${escapeHtml(item.lib_reference)}</strong>
              ${lcscBadge}
            </div>
            <code class="small text-muted">${escapeHtml(item.package || '-')}</code>
          </a>
        `;
      });
    }

    // 4. KiCad Matches
    if (data.kicad && data.kicad.items && data.kicad.items.length > 0) {
      html += `
        <div class="px-3 py-1 bg-light text-uppercase fw-bold text-secondary border-bottom" style="font-size: 0.72rem; letter-spacing: 0.5px;">
          ${navI18n.card_kicad_title || 'KiCad'} (${data.kicad.total})
        </div>
      `;
      data.kicad.items.forEach(item => {
        html += `
          <a href="${item.url}" class="dropdown-item py-2 px-3 border-bottom d-flex justify-content-between align-items-center">
            <div class="text-truncate me-2">
              <span class="badge bg-secondary me-1">KiCad</span>
              <strong class="text-dark">${escapeHtml(item.name)}</strong>
              <small class="text-muted ms-1">${escapeHtml(item.library || '')}</small>
            </div>
            <code class="small text-muted text-truncate" style="max-width: 120px;">${escapeHtml(item.footprint || '-')}</code>
          </a>
        `;
      });
    }

    // 5. Fasteners Matches
    if (data.fasteners && data.fasteners.items && data.fasteners.items.length > 0) {
      html += `
        <div class="px-3 py-1 bg-light text-uppercase fw-bold text-secondary border-bottom" style="font-size: 0.72rem; letter-spacing: 0.5px;">
          ${navI18n.nav_lib_fasteners || 'Mechanical'} (${data.fasteners.total})
        </div>
      `;
      data.fasteners.items.forEach(item => {
        html += `
          <a href="${item.url}" class="dropdown-item py-2 px-3 border-bottom d-flex justify-content-between align-items-center">
            <div class="text-truncate me-2">
              <span class="badge bg-info text-dark me-1">${escapeHtml(item.authority || 'STD')}</span>
              <strong class="text-dark">${escapeHtml(item.name)}</strong>
              <small class="text-muted ms-1">${escapeHtml(item.category || '')}</small>
            </div>
            <code class="small text-muted text-truncate" style="max-width: 120px;">${escapeHtml(item.authority || '')}</code>
          </a>
        `;
      });
    }

    // Footer: View All
    html += `
      <div class="p-2 bg-light text-center">
        <a href="/search?q=${encodeURIComponent(query)}" class="btn btn-primary btn-sm w-100 fw-bold">
          ${navI18n.live_view_all || 'View All Results'} (${total.toLocaleString()}) &rarr;
        </a>
      </div>
    `;

    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
  }

  // Input event with 250ms debounce
  searchInput.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    const q = this.value.trim();
    if (q.length < 1) {
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
      return;
    }
    debounceTimer = setTimeout(() => {
      fetchQuickSearch(q);
    }, 250);
  });

  // Re-show dropdown on focus if input has value
  searchInput.addEventListener('focus', function() {
    const q = this.value.trim();
    if (q.length >= 1 && dropdown.innerHTML.trim().length > 0) {
      dropdown.style.display = 'block';
    }
  });

  // Dismiss on clicking outside
  document.addEventListener('click', function(e) {
    if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });

  // Dismiss on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      dropdown.style.display = 'none';
    }
  });

})();
