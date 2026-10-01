const I18N = JSON.parse(document.getElementById('page-translations').textContent);
      const urlParams = new URLSearchParams(window.location.search);
      const projectId = urlParams.get("project_id");
      const bomImportLink = document.getElementById("importBomButton");
      let isSystemProject = false;
      let selectableInventoryParts = [];

      function updateSelectedPartLink() {
        const selectedId = document.getElementById("partSelect").value;
        const part = selectableInventoryParts.find(item => String(item.id) === selectedId);
        const link = document.getElementById("project-selected-part-link");
        link.hidden = !part;
        if (part) {
          link.textContent = part.name;
          link.href = window.ComponentLinks.detailUrl({part_id: part.id});
        } else link.removeAttribute("href");
      }

      if (projectId && bomImportLink) {
        bomImportLink.href = `/bom-import?project_id=${encodeURIComponent(projectId)}`;
      }

      if (!projectId) {
        alert(I18N.missing_project_id);
        window.location.href = "/projects";
      }

      function loadProjectDetails() {
        fetch(`/api/projects/${projectId}`)
          .then(res => {
            if (!res.ok) throw new Error(I18N.alert_fetch_failed);
            return res.json();
          })
          .then(data => {
            isSystemProject = Boolean(data.is_system);
            document.getElementById("project-actions").classList.toggle("d-none", isSystemProject);
            document.getElementById("project-actions-header").classList.toggle("d-none", isSystemProject);
            document.getElementById("project-shortage-card").classList.toggle("d-none", isSystemProject);
            document.getElementById("loose-parts-hint").hidden = !isSystemProject;
            document.getElementById("project-name").textContent = data.name;
            document.getElementById("project-description").textContent = data.description || I18N.no_description;
            document.getElementById("project-parts-count").textContent = data.parts_count || 0;
            document.getElementById("project-available-total").textContent = data.total_available_quantity || 0;

            renderBomTable(data.parts || []);
            renderShortageTable(data.parts || []);
          })
          .catch(err => {
            console.error("Error loading project details:", err);
            alert(I18N.alert_fetch_failed);
          });
      }

      function renderBomTable(parts) {
        const tbody = document.getElementById("bom-table-body");
        tbody.innerHTML = "";
        if (!parts || parts.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">${I18N.empty_bom_hint}</td></tr>`;
          return;
        }

        parts.forEach(p => {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td>
              <a href="/component_details?part_id=${p.part_id}" class="fw-bold text-decoration-none">
                ${p.part_name}
              </a>
            </td>
            <td>${p.manufacturer || '-'}</td>
            <td><code>${p.package || '-'}</code></td>
            <td><span class="badge bg-info text-dark">${p.part_type || '-'}</span></td>
            <td data-sort-value="${p.quantity_available}">
              <span class="badge ${p.quantity_available > 0 ? 'bg-success' : 'bg-danger'}">
                ${p.quantity_available}
              </span>
            </td>
            <td class="fw-bold text-primary" data-sort-value="${p.quantity_needed || 0}">${p.quantity_needed || 0}</td>
            <td data-sort-value="${p.shortage || 0}">
              <span class="badge ${p.shortage > 0 ? 'bg-danger' : 'bg-success'}">
                ${p.shortage > 0 ? `缺 ${p.shortage}` : '充足'}
              </span>
            </td>
            <td class="text-end ${isSystemProject ? 'd-none' : ''}">
              <button class="btn btn-outline-secondary btn-sm me-1" onclick="editQuantity(${p.part_id}, ${p.quantity_needed || 0})">
                ${I18N.btn_edit_qty}
              </button>
              <button class="btn btn-outline-danger btn-sm" onclick="removePart(${p.part_id})">
                ${I18N.btn_remove}
              </button>
            </td>
          `;
          tbody.appendChild(row);
        });
      }

      function renderShortageTable(parts) {
        const tbody = document.getElementById("shortage-table-body");
        const alertBox = document.getElementById("no-shortage-alert");
        const table = document.getElementById("shortage-table");
        tbody.innerHTML = "";

        const shortageParts = parts.filter(p => p.shortage > 0);
        if (shortageParts.length === 0) {
          table.style.display = "none";
          alertBox.style.display = "block";
          return;
        }

        table.style.display = "table";
        alertBox.style.display = "none";

        shortageParts.forEach(p => {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td><a href="/component_details?part_id=${p.part_id}" class="fw-bold text-decoration-none">${p.part_name}</a></td>
            <td><code>${p.package || '-'}</code></td>
            <td data-sort-value="${p.quantity_available}"><span class="badge bg-secondary">${p.quantity_available}</span></td>
            <td data-sort-value="${p.quantity_needed || 0}">${p.quantity_needed || 0}</td>
            <td class="text-danger fw-bold fs-6" data-sort-value="${p.shortage}">-${p.shortage}</td>
          `;
          tbody.appendChild(row);
        });
      }

      function loadInventoryForSelect() {
        fetch("/api/inventory/get_parts_inventory")
          .then(res => res.json())
          .then(parts => {
            selectableInventoryParts = parts;
            const select = document.getElementById("partSelect");
            select.innerHTML = '<option value="">-- 请选择 / Select --</option>';
            parts.forEach(p => {
              const opt = document.createElement("option");
              opt.value = p.id;
              opt.textContent = `${p.name} (${p.package || '-'}, 库存: ${p.quantity})`;
              select.appendChild(opt);
            });
            updateSelectedPartLink();
          })
          .catch(err => console.error("Error loading inventory for select:", err));
      }

      function submitAddPart() {
        const partId = document.getElementById("partSelect").value;
        const qtyVal = document.getElementById("neededQuantity").value.trim();
        const quantityNeeded = qtyVal ? parseInt(qtyVal, 10) : 0;

        if (!partId) return;

        fetch(`/api/projects/${projectId}/add_part`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            part_id: parseInt(partId, 10),
            quantity_needed: isNaN(quantityNeeded) ? 0 : quantityNeeded
          })
        })
        .then(res => {
          if (!res.ok) throw new Error(I18N.alert_add_failed);
          return res.json();
        })
        .then(() => {
          const modalEl = document.getElementById('addPartModal');
          const modal = bootstrap.Modal.getInstance(modalEl);
          if (modal) modal.hide();
          document.getElementById("addPartForm").reset();
          updateSelectedPartLink();
          loadProjectDetails();
        })
        .catch(err => {
          console.error("Error adding part:", err);
          alert(I18N.alert_add_failed);
        });
      }

      function editQuantity(partId, currentQty) {
        const input = prompt(I18N.prompt_new_qty, currentQty);
        if (input === null) return;
        const newQty = parseInt(input.trim(), 10);
        if (isNaN(newQty) || newQty < 0) {
          alert("请输入有效的非负整数");
          return;
        }

        fetch(`/api/projects/${projectId}/update_part_quantity?part_id=${partId}&quantity_needed=${newQty}`, {
          method: 'POST'
        })
        .then(res => {
          if (!res.ok) throw new Error(I18N.alert_update_failed);
          return res.json();
        })
        .then(() => {
          loadProjectDetails();
        })
        .catch(err => {
          console.error("Error updating quantity:", err);
          alert(I18N.alert_update_failed);
        });
      }

      function removePart(partId) {
        if (!window.confirm(I18N.confirm_remove_part)) return;

        fetch(`/api/projects/${projectId}/remove_part/${partId}`, {
          method: 'DELETE'
        })
        .then(res => {
          if (!res.ok) throw new Error(I18N.alert_remove_failed);
          return res.json();
        })
        .then(() => {
          loadProjectDetails();
        })
        .catch(err => {
          console.error("Error removing part:", err);
          alert(I18N.alert_remove_failed);
        });
      }

      document.getElementById("partSelect").addEventListener("change", updateSelectedPartLink);
      document.addEventListener("DOMContentLoaded", () => {
        loadProjectDetails();
        loadInventoryForSelect();
      });
