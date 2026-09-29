const symId = document.getElementById('detailContainer')?.dataset?.symId || window.location.pathname.split('/').filter(Boolean).pop();
      const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      let rawSexprText = '';

      async function loadSymbolDetails() {
        try {
          const res = await fetch(`/api/libraries/kicad/${symId}`);
          if (!res.ok) throw new Error('Not found');
          const data = await res.json();
          renderDetails(data);
        } catch (e) {
          document.getElementById('loadingContainer').innerHTML =
            `<div class="alert alert-danger">${i18n.no_data || 'Symbol not found.'}</div>`;
        }
      }

      function renderDetails(data) {
        document.getElementById('loadingContainer').style.display = 'none';
        document.getElementById('contentContainer').style.display = 'block';

        document.getElementById('symbolName').textContent = data.name || '-';
        document.getElementById('symbolValue').textContent = data.value || data.name || '';

        // Badges
        const badges = document.getElementById('headerBadges');
        badges.innerHTML = '';
        if (data.library) {
          badges.innerHTML += `<span class="badge bg-secondary">${escapeHtml(data.library)}</span>`;
        }
        if (data.reference) {
          badges.innerHTML += `<span class="badge bg-dark">Ref: ${escapeHtml(data.reference)}</span>`;
        }
        if (data.extends) {
          badges.innerHTML += `<span class="badge bg-info text-dark">Extends: ${escapeHtml(data.extends)}</span>`;
        }

        // Basic
        document.getElementById('propName').textContent = data.name || '-';
        document.getElementById('propValue').textContent = data.value || '-';
        document.getElementById('propLibrary').textContent = data.library || '-';
        document.getElementById('propReference').textContent = data.reference || '-';
        document.getElementById('propExtends').textContent = data.extends || '-';
        document.getElementById('propFootprint').textContent = data.footprint || '-';
        document.getElementById('propSourceFile').textContent = data.source_file || '-';

        // Flags
        document.getElementById('propInBom').innerHTML = data.in_bom === 1 ?
          '<span class="badge bg-success">Yes</span>' : '<span class="badge bg-secondary">No</span>';
        document.getElementById('propOnBoard').innerHTML = data.on_board === 1 ?
          '<span class="badge bg-success">Yes</span>' : '<span class="badge bg-secondary">No</span>';
        document.getElementById('propFpFilters').textContent = data.fp_filters || '-';
        document.getElementById('propKeywords').textContent = data.keywords || '-';
        document.getElementById('propDescription').textContent = data.description || '-';

        // Actions
        const actions = document.getElementById('headerActions');
        actions.innerHTML = `
          <button class="btn btn-success btn-sm me-2 text-nowrap" onclick="openImportModal('kicad', '${data.id}', '${escapeHtml(data.name)}', '${escapeHtml(data.footprint || '')} | ${escapeHtml(data.library || '')}')">
            ${i18n.btn_quick_add || '+ Add to Inventory'}
          </button>
        `;
        if (data.datasheet && data.datasheet !== '~') {
          actions.innerHTML += `
            <a href="${data.datasheet}" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm text-nowrap">
              ${i18n.external_datasheet || 'Datasheet (PDF)'}
            </a>`;
        }

        // Properties table
        const propsTbody = document.getElementById('propsTableBody');
        propsTbody.innerHTML = '';
        const props = data.properties || {};
        const keys = Object.keys(props);
        if (keys.length === 0) {
          propsTbody.innerHTML = `<tr><td colspan="2" class="text-center text-muted py-3">${i18n.no_data || 'No properties available'}</td></tr>`;
        } else {
          keys.forEach(k => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td class="fw-bold text-secondary">${escapeHtml(k)}</td>
              <td>${escapeHtml(String(props[k]))}</td>
            `;
            propsTbody.appendChild(tr);
          });
        }

        // S-expression
        rawSexprText = data.raw_sexpr || '';
        document.getElementById('rawSexprBlock').textContent = rawSexprText;
      }

      document.getElementById('copySexprBtn').addEventListener('click', async () => {
        if (!rawSexprText) return;
        try {
          await navigator.clipboard.writeText(rawSexprText);
          const btn = document.getElementById('copySexprBtn');
          const original = btn.textContent;
          btn.textContent = i18n.copied || 'Copied!';
          btn.className = 'btn btn-success btn-sm';
          setTimeout(() => {
            btn.textContent = original;
            btn.className = 'btn btn-outline-secondary btn-sm';
          }, 2000);
        } catch (e) {
          console.error('Clipboard copy failed', e);
        }
      });

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      loadSymbolDetails();
