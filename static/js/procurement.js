const I18N = JSON.parse(document.getElementById('page-translations').textContent);
      const tbody = document.getElementById("procurement-table-body");

      function loadProcurementList() {
        fetch("/api/projects/procurement/list")
          .then(res => {
            if (!res.ok) throw new Error(I18N.alert_fetch_failed);
            return res.json();
          })
          .then(items => {
            tbody.innerHTML = "";
            if (!items || items.length === 0) {
              tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-5">${I18N.empty_hint}</td></tr>`;
              return;
            }

            items.forEach(item => {
              const projectBadges = (item.projects && item.projects.length > 0)
                ? item.projects.map(p => `
                    <a href="/project_details?project_id=${p.id}" class="badge bg-secondary text-decoration-none me-1 mb-1">
                      ${p.name} (需 ${p.quantity_needed || 0})
                    </a>
                  `).join('')
                : '-';

              const row = document.createElement("tr");
              row.innerHTML = `
                <td>
                  <a href="/component_details?part_id=${item.part_id}" class="fw-bold text-decoration-none">
                    ${item.part_name}
                  </a>
                </td>
                <td><code>${item.package || '-'}</code></td>
                <td><span class="badge bg-info text-dark">${item.part_type || '-'}</span></td>
                <td class="text-center">
                  <span class="badge ${item.quantity_available > 0 ? 'bg-success' : 'bg-danger'}">
                    ${item.quantity_available}
                  </span>
                </td>
                <td class="text-center fw-bold text-primary">${item.total_needed}</td>
                <td class="text-center">
                  <span class="badge ${item.shortage > 0 ? 'bg-danger fs-6' : 'bg-success'}">
                    ${item.shortage > 0 ? `缺 ${item.shortage}` : '充足'}
                  </span>
                </td>
                <td>${projectBadges}</td>
              `;
              tbody.appendChild(row);
            });
          })
          .catch(err => {
            console.error("Error loading procurement list:", err);
            alert(I18N.alert_fetch_failed);
          });
      }

      document.addEventListener("DOMContentLoaded", loadProcurementList);
