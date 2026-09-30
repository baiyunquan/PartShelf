const I18N = JSON.parse(document.getElementById('page-translations').textContent);
      const tbody = document.getElementById("projects-table-body");

      function renderProjects(projects) {
        tbody.innerHTML = "";
        if (!projects || projects.length === 0) {
          const emptyRow = document.createElement("tr");
          emptyRow.innerHTML = `<td colspan="5" class="text-center text-muted py-4">${I18N.empty_hint}</td>`;
          tbody.appendChild(emptyRow);
          return;
        }

        projects.forEach(p => {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td data-sort-value="${p.id}"><span class="badge bg-light text-dark border">#${p.id}</span></td>
            <td class="fw-bold">${p.name}</td>
            <td class="text-secondary">${p.description || '-'}</td>
            <td class="text-center" data-sort-value="${p.parts_count || 0}">
              <span class="badge ${p.parts_count > 0 ? 'bg-primary' : 'bg-secondary'}">
                ${p.parts_count}
              </span>
              <small class="d-block text-muted">${I18N.available_total}: ${p.total_available_quantity || 0}</small>
            </td>
            <td class="text-end">
              <a href="/project_details?project_id=${p.id}" class="btn btn-outline-primary btn-sm me-1">
                ${I18N.btn_details}
              </a>
              ${p.is_system ? '' : `<button class="btn btn-outline-danger btn-sm" onclick="deleteProject(${p.id})">${I18N.btn_delete}</button>`}
            </td>
          `;
          tbody.appendChild(row);
        });
      }

      function loadProjects() {
        fetch("/api/projects/")
          .then(res => {
            if (!res.ok) throw new Error(I18N.alert_fetch_failed);
            return res.json();
          })
          .then(data => renderProjects(data))
          .catch(err => {
            console.error("Error loading projects:", err);
            alert(I18N.alert_fetch_failed);
          });
      }

      function deleteProject(id) {
        if (!window.confirm(I18N.confirm_delete)) return;

        fetch(`/api/projects/${id}`, {
          method: 'DELETE'
        })
        .then(res => {
          if (!res.ok) throw new Error(I18N.alert_delete_failed);
          return res.json();
        })
        .then(() => {
          loadProjects();
        })
        .catch(err => {
          console.error("Error deleting project:", err);
          alert(I18N.alert_delete_failed);
        });
      }

      document.addEventListener("DOMContentLoaded", loadProjects);
