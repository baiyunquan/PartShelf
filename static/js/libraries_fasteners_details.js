const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      const standardCode = document.getElementById('detailContainer')?.dataset?.standardCode || decodeURIComponent(window.location.pathname.split('/').filter(Boolean).pop());

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      async function loadDetail() {
        try {
          const res = await fetch(`/api/libraries/fasteners/${encodeURIComponent(standardCode)}`);
          if (!res.ok) throw new Error('Fastener standard not found');
          const data = await res.json();
          renderDetail(data);
        } catch (err) {
          document.getElementById('loadingContainer').innerHTML = `
            <div class="text-danger py-4">
              <h5>无法加载紧固件标准数据</h5>
              <p class="small text-muted">${escapeHtml(err.message)}</p>
              <a href="/libraries/fasteners" class="btn btn-outline-secondary btn-sm mt-2">返回标准列表</a>
            </div>
          `;
        }
      }

      function renderDetail(data) {
        const std = data.standard || {};
        document.getElementById('badgeAuthority').textContent = std.authority || 'STD';

        const DOMAIN_LABELS = {
          'fasteners': i18n['libraries_fasteners.domain_fasteners'] || '紧固件',
          'power_transmission': i18n['libraries_fasteners.domain_power_transmission'] || '动力传动',
          'structural_materials': i18n['libraries_fasteners.domain_structural_materials'] || '结构材料 / 型材'
        };
        const DOMAIN_BADGES = {
          'fasteners': 'badge bg-secondary fs-6',
          'power_transmission': 'badge bg-info-subtle text-info-emphasis border border-info-subtle fs-6',
          'structural_materials': 'badge bg-warning-subtle text-warning-emphasis border border-warning-subtle fs-6'
        };
        const domBadge = document.getElementById('badgeDomain');
        if (domBadge) {
          domBadge.textContent = DOMAIN_LABELS[std.domain] || std.domain || '紧固件';
          domBadge.className = DOMAIN_BADGES[std.domain] || 'badge bg-secondary fs-6';
        }

        document.getElementById('badgeCategory').textContent = std.category_group_zh || std.category_group || '-';
        document.getElementById('stdTitle').textContent = std.standard_name || std.standard_code;
        document.getElementById('stdDesc').textContent = std.description || '标准构件定义';
        document.getElementById('badgeSourceFile').textContent = std.source_file || 'FsData';

        const nominalSelect = document.getElementById('detailFastenerNominal');
        const lengthSelect = document.getElementById('detailFastenerLength');
        const lengthGroup = document.getElementById('detailFastenerLengthGroup');
        const addVariantButton = document.getElementById('addFastenerVariantBtn');
        if (nominalSelect && addVariantButton) {
          nominalSelect.replaceChildren();
          (data.param_rows || []).forEach(row => {
            const option = document.createElement('option');
            option.value = row.nominal;
            option.textContent = row.nominal;
            nominalSelect.appendChild(option);
          });
          lengthSelect.replaceChildren();
          (data.length_rows || []).forEach(row => {
            const option = document.createElement('option');
            option.value = row.key;
            option.textContent = row.key;
            lengthSelect.appendChild(option);
          });
          const needsLength = Boolean(std.has_length);
          lengthGroup.style.display = needsLength ? '' : 'none';
          addVariantButton.disabled = !nominalSelect.options.length ||
            (needsLength && !lengthSelect.options.length);
          addVariantButton.addEventListener('click', () => {
            const nominal = nominalSelect.value;
            const length = needsLength ? lengthSelect.value : null;
            if (!nominal || (needsLength && !length)) return;
            const externalId = window.buildFastenerVariantId(std.standard_code, nominal, length);
            const size = length ? `${nominal} × ${length}${String(length).toLowerCase().includes('in') ? '' : ' mm'}` : nominal;
            const name = `${std.standard_code} ${size}`;
            const meta = `${std.authority || ''} | ${std.category_group_zh || std.category_group || ''}`;
            window.openImportModal('fasteners', externalId, name, meta, 1);
          });
        }

        // 1. Render Param Matrix
        const thead = document.getElementById('paramTableHead');
        const tbody = document.getElementById('paramTableBody');
        const titles = data.param_titles || [];
        const rows = data.param_rows || [];
        const tapHoles = data.tap_holes || {};

        document.getElementById('paramTableNameDisplay').textContent = std.param_table_name ? `参数表: ${std.param_table_name}` : '';

        let thHtml = '<tr><th class="bg-dark text-white text-center" style="min-width: 90px;">公称直径</th>';
        titles.forEach(t => {
          thHtml += `<th class="bg-dark text-white text-center">${escapeHtml(String(t))}</th>`;
        });
        thHtml += '<th class="bg-secondary text-white text-center" style="min-width: 120px;">建议攻丝底孔</th></tr>';
        thead.innerHTML = thHtml;

        if (rows.length === 0) {
          tbody.innerHTML = `<tr><td colspan="${titles.length + 2}" class="text-center py-4 text-muted">暂无尺寸参数表记录</td></tr>`;
        } else {
          let tbHtml = '';
          rows.forEach(r => {
            const nom = r.nominal || '';
            const tapHole = tapHoles[nom] !== undefined ? `${tapHoles[nom]} mm` : '-';
            tbHtml += `<tr><td class="fw-bold bg-light text-primary text-center">${escapeHtml(nom)}</td>`;
            r.values.forEach(v => {
              tbHtml += `<td class="text-center">${escapeHtml(String(v))}</td>`;
            });
            tbHtml += `<td class="text-center text-success fw-bold">${escapeHtml(tapHole)}</td></tr>`;
          });
          tbody.innerHTML = tbHtml;
        }

        // 2. Render Length Series
        const lengthRows = data.length_rows || [];
        if (lengthRows.length > 0) {
          const lCard = document.getElementById('lengthCard');
          const lContainer = document.getElementById('lengthListContainer');
          document.getElementById('lengthTableNameDisplay').textContent = std.length_table_name ? `长度表: ${std.length_table_name}` : '';

          let lHtml = '';
          lengthRows.forEach(lr => {
            const key = lr.key || '';
            const lengths = lr.lengths || [];
            lHtml += `
              <div class="p-3 bg-light rounded border">
                <div class="fw-bold mb-2 text-dark">${escapeHtml(key)} 可用公称长度系列：</div>
                <div class="d-flex flex-wrap gap-1">
                  ${lengths.map(len => `<span class="badge bg-white text-dark border px-2 py-1">${escapeHtml(String(len))} mm</span>`).join('')}
                </div>
              </div>
            `;
          });
          lContainer.innerHTML = lHtml;
          lCard.style.display = 'block';
        }

        // 3. Render Assembly Guide (Torque & Wrench)
        const guides = data.assembly_guides || [];
        const torqueBody = document.getElementById('torqueTableBody');
        const wrenchBody = document.getElementById('wrenchTableBody');
        const guideCard = document.getElementById('assemblyGuideCard');

        if (guides.length === 0) {
          if (guideCard) guideCard.style.display = 'none';
        } else {
          if (guideCard) guideCard.style.display = 'block';
          let torqueHtml = '';
          let wrenchHtml = '';

          guides.forEach(g => {
            const isCurr = g.is_current;
            const rowClass = isCurr ? 'table-warning fw-bold' : '';
            const nomBadge = isCurr
              ? `<span class="badge bg-warning text-dark me-1">当前</span><span class="text-primary">${escapeHtml(g.nominal)}</span>`
              : `<span class="text-dark">${escapeHtml(g.nominal)}</span>`;

            torqueHtml += `
              <tr class="${rowClass}">
                <td>${nomBadge}</td>
                <td>${g.stress_area || '-'}</td>
                <td>${g.preload_8_8 || '-'}</td>
                <td class="${isCurr ? 'text-primary' : ''}">${g.dry_torque_8_8 || '-'}</td>
                <td class="${isCurr ? 'text-success' : ''}">${g.lube_torque_8_8 || '-'}</td>
                <td>${g.preload_10_9 || '-'}</td>
                <td class="${isCurr ? 'text-primary' : ''}">${g.dry_torque_10_9 || '-'}</td>
                <td class="${isCurr ? 'text-success' : ''}">${g.lube_torque_10_9 || '-'}</td>
                <td>${g.preload_12_9 || '-'}</td>
                <td class="${isCurr ? 'text-primary' : ''}">${g.dry_torque_12_9 || '-'}</td>
                <td class="${isCurr ? 'text-success' : ''}">${g.lube_torque_12_9 || '-'}</td>
              </tr>
            `;

            wrenchHtml += `
              <tr class="${rowClass}">
                <td>${nomBadge}</td>
                <td>${escapeHtml(g.hex_wrench_af ? g.hex_wrench_af + ' mm' : '-')}</td>
                <td>${escapeHtml(g.socket_size ? g.socket_size + ' mm' : '-')}</td>
                <td>${escapeHtml(g.hex_key ? g.hex_key + ' mm' : '-')}</td>
              </tr>
            `;
          });

          if (torqueBody) torqueBody.innerHTML = torqueHtml;
          if (wrenchBody) wrenchBody.innerHTML = wrenchHtml;
        }

        document.getElementById('loadingContainer').style.display = 'none';
        document.getElementById('detailContainer').style.display = 'block';
      }

      document.addEventListener('DOMContentLoaded', loadDetail);
