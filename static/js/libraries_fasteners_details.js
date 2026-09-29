const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
      const fastenerI18n = i18n.libraries_fasteners || {};
      const tr = (key, fallback) => fastenerI18n[key] || i18n[`libraries_fasteners.${key}`] || fallback;
      const standardCode = document.getElementById('detailContainer')?.dataset?.standardCode || decodeURIComponent(window.location.pathname.split('/').filter(Boolean).pop());

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[m]);
      }

      function setupCustomSpecForm(standard, titles) {
        const toggle = document.getElementById('customFastenerSpecToggle');
        const panel = document.getElementById('customFastenerSpecPanel');
        const fields = document.getElementById('customFastenerSpecFields');
        const form = document.getElementById('customFastenerSpecForm');
        if (!toggle || !panel || !fields || !form) return;

        toggle.onclick = () => {
          panel.hidden = !panel.hidden;
          toggle.setAttribute('aria-expanded', String(!panel.hidden));
        };

        const requiredForInsert = new Set(['length', 'extdia']);
        let html = `
          <div class="col-md-4">
            <label class="form-label fw-semibold" for="customSpecNominal">${escapeHtml(tr('custom_spec_nominal', 'Nominal Size'))}</label>
            <input class="form-control" id="customSpecNominal" name="nominal" type="text" maxlength="100" required>
          </div>`;
        titles.forEach((title, index) => {
          const required = standard.standard_code === 'IUTHeatInsert' && requiredForInsert.has(String(title).toLowerCase());
          const id = `customSpecDimension${index}`;
          html += `
            <div class="col-md-4">
              <label class="form-label fw-semibold" for="${id}">${escapeHtml(String(title))}${required ? '' : ` <span class="text-muted small">(${escapeHtml(tr('custom_spec_optional', 'Optional'))})</span>`}</label>
              <input class="form-control" id="${id}" type="number" min="0" step="any" data-dimension-title="${escapeHtml(String(title))}"${required ? ' required' : ''}>
            </div>`;
        });
        if (standard.length_table_name) {
          const lengthUnit = standard.length_unit || 'mm';
          html += `
            <div class="col-md-4">
              <label class="form-label fw-semibold" for="customSpecLength">${escapeHtml(tr('custom_spec_length', 'Custom Length'))} (${escapeHtml(lengthUnit)}) <span class="text-muted small">(${escapeHtml(tr('custom_spec_optional', 'Optional'))})</span></label>
              <input class="form-control" id="customSpecLength" type="number" min="0" step="any">
            </div>`;
        }
        fields.innerHTML = html;

        if (form.dataset.bound === 'true') return;
        form.dataset.bound = 'true';
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const status = document.getElementById('customFastenerSpecStatus');
          const submit = document.getElementById('customFastenerSpecSubmit');
          if (!form.reportValidity()) {
            status.textContent = tr('custom_spec_missing', 'Fill in the required dimension fields.');
            status.className = 'small mt-3 text-danger';
            return;
          }
          const dimensions = {};
          fields.querySelectorAll('[data-dimension-title]').forEach(input => {
            dimensions[input.dataset.dimensionTitle] = input.value.trim() === '' ? null : input.value;
          });
          const payload = { nominal: document.getElementById('customSpecNominal').value.trim(), dimensions };
          const lengthInput = document.getElementById('customSpecLength');
          if (lengthInput && lengthInput.value.trim()) payload.length = lengthInput.value.trim();
          submit.disabled = true;
          status.textContent = tr('custom_spec_saving', 'Saving...');
          status.className = 'small mt-3 text-muted';
          try {
            const response = await fetch(`/api/libraries/fasteners/${encodeURIComponent(standard.standard_code)}/specs`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || tr('custom_spec_error', 'Could not save the specification.'));
            status.textContent = tr('custom_spec_saved', 'Specification saved.');
            status.className = 'small mt-3 text-success';
            window.setTimeout(() => window.location.reload(), 500);
          } catch (error) {
            status.textContent = error.message || tr('custom_spec_error', 'Could not save the specification.');
            status.className = 'small mt-3 text-danger';
          } finally {
            submit.disabled = false;
          }
        });
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
          'fasteners': tr('domain_fasteners', 'Fasteners'),
          'power_transmission': tr('domain_power_transmission', 'Power Transmission'),
          'structural_materials': tr('domain_structural_materials', 'Structural Materials & Profiles')
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
        document.getElementById('stdTitle').textContent = std.standard_name_localized || std.standard_name || std.standard_code;
        document.getElementById('stdDesc').textContent = [std.standard_name, std.description].filter(Boolean).join(' · ') || '标准构件定义';
        document.getElementById('badgeSourceFile').textContent = std.source_file || 'FsData';

        const nominalSelect = document.getElementById('detailFastenerNominal');
        const lengthSelect = document.getElementById('detailFastenerLength');
        const lengthGroup = document.getElementById('detailFastenerLengthGroup');
        const addVariantButton = document.getElementById('addFastenerVariantBtn');
        if (nominalSelect && addVariantButton) {
          nominalSelect.replaceChildren();
          (data.param_rows || []).forEach(row => {
            const option = document.createElement('option');
            option.value = row.row_key || row.nominal;
            const valuesLabel = row.is_custom ? ` (${(row.values || []).filter(value => value !== null).join(' × ')})` : '';
            option.textContent = `${row.nominal}${row.is_custom ? ` — ${tr('custom_spec_custom_badge', 'User specification')}${valuesLabel}` : ''}`;
            option.dataset.custom = row.is_custom ? 'true' : 'false';
            option.dataset.nominal = row.nominal;
            option.dataset.customLength = row.custom_length || '';
            option.dataset.customValues = row.is_custom
              ? (row.values || []).map((value, index) => value === null || value === undefined
                ? null
                : `${titles[index]}=${value}`).filter(Boolean).join(', ')
              : '';
            nominalSelect.appendChild(option);
          });
          lengthSelect.replaceChildren();
          (data.length_rows || []).filter(row => !row.is_custom).forEach(row => {
            const option = document.createElement('option');
            option.value = row.key;
            option.textContent = row.custom_length || row.key;
            lengthSelect.appendChild(option);
          });
          const needsLength = Boolean(std.has_length);
          const updateVariantAvailability = () => {
            const selected = nominalSelect.selectedOptions[0];
            const isCustom = selected?.dataset.custom === 'true';
            const customLength = selected?.dataset.customLength || '';
            lengthGroup.style.display = needsLength && !(isCustom && customLength) ? '' : 'none';
            addVariantButton.disabled = !selected || (needsLength && !(isCustom && customLength) && !lengthSelect.options.length) ||
              (needsLength && isCustom && !customLength);
          };
          updateVariantAvailability();
          nominalSelect.onchange = updateVariantAvailability;
          addVariantButton.addEventListener('click', () => {
            const selected = nominalSelect.selectedOptions[0];
            const nominal = selected?.dataset.nominal || '';
            const isCustom = selected?.dataset.custom === 'true';
            const length = needsLength && !isCustom ? lengthSelect.value : (selected?.dataset.customLength || null);
            if (!nominal || (needsLength && !length)) return;
            const externalId = isCustom
              ? window.buildCustomFastenerVariantId(std.standard_code, nominalSelect.value)
              : window.buildFastenerVariantId(std.standard_code, nominal, length);
            const size = length ? `${nominal} × ${length}${String(length).toLowerCase().includes('in') ? '' : ' mm'}` : nominal;
            const customValues = selected?.dataset.customValues ? ` [${selected.dataset.customValues}]` : '';
            const name = `${std.standard_code} ${size}${customValues}`;
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
        setupCustomSpecForm(std, titles);

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
            tbHtml += `<tr><td class="fw-bold bg-light text-primary text-center">${escapeHtml(nom)}${r.is_custom ? `<br><span class="badge bg-info-subtle text-info-emphasis">${escapeHtml(tr('custom_spec_custom_badge', 'User specification'))}</span>` : ''}</td>`;
            r.values.forEach(v => {
              tbHtml += `<td class="text-center">${v === null || v === undefined ? '-' : escapeHtml(String(v))}</td>`;
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
                <div class="fw-bold mb-2 text-dark">${escapeHtml(lr.custom_length ? `${lr.nominal} × ${lr.custom_length}` : key)} 可用公称长度系列：</div>
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
