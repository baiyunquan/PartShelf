/**
 * bom_import.js
 * Controls BOM (CSV / XLSX) upload, interactive matching preview,
 * component binding, and import execution for PartShelf.
 */

(function () {
  let _parsedData = null;
  let _currentBindingRowIndex = null;
  let _projectsLoaded = false;
  let _preselectedProjectId = null;

  // DOM Elements
  const modalEl = document.getElementById("bomImportModal");
  if (!modalEl) return;

  const stage1 = document.getElementById("bomStage1");
  const stage2 = document.getElementById("bomStage2");
  const btnParse = document.getElementById("btnBomParsePreview");
  const btnBack = document.getElementById("btnBomBack");
  const btnConfirm = document.getElementById("btnBomConfirmImport");

  const fileInput = document.getElementById("bomFileInput");
  const targetNewRadio = document.getElementById("bomTargetNew");
  const targetExistingRadio = document.getElementById("bomTargetExisting");
  const newFields = document.getElementById("bomNewProjectFields");
  const existingFields = document.getElementById("bomExistingProjectFields");
  const projectNameInput = document.getElementById("bomProjectName");
  const projectDescInput = document.getElementById("bomProjectDesc");
  const existingSelect = document.getElementById("bomExistingProjectSelect");

  const tbody = document.getElementById("bomPreviewTbody");
  const selectAllCb = document.getElementById("bomSelectAllCb");

  // Summary Counters
  const summaryTotal = document.getElementById("bomSummaryTotal");
  const summaryInInv = document.getElementById("bomSummaryInInventory");
  const summaryMatchedLib = document.getElementById("bomSummaryMatchedLib");
  const summaryUnmatched = document.getElementById("bomSummaryUnmatched");
  const skippedSummary = document.getElementById("bomSkippedSummary");
  const targetSummaryText = document.getElementById("bomTargetSummaryText");

  // Sub-modal elements
  const searchModalEl = document.getElementById("bomSearchBindModal");
  const bindSearchInput = document.getElementById("bomBindSearchInput");
  const bindSearchBtn = document.getElementById("bomBindSearchBtn");
  const bindSearchResults = document.getElementById("bomBindSearchResults");

  const customModalEl = document.getElementById("bomCustomPartModal");
  const customNameInput = document.getElementById("bomCustomName");
  const customMfrInput = document.getElementById("bomCustomMfr");
  const customPkgInput = document.getElementById("bomCustomPackage");
  const customDescInput = document.getElementById("bomCustomDesc");
  const btnSaveCustom = document.getElementById("btnBomSaveCustom");

  function getI18n() {
    const el = document.getElementById("page-translations");
    return el ? JSON.parse(el.textContent || "{}") : {};
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str).replace(/[&<>"']/g, (m) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[m]);
  }

  function librarySourceName(source) {
    if (source === "jlcparts") return "JLCPCB";
    if (source === "fasteners") return getI18n().tab_fasteners || "Fasteners";
    return source || "";
  }

  // Load existing projects for select dropdown
  async function loadExistingProjects() {
    if (_projectsLoaded) return;
    try {
      const res = await fetch("/api/projects/");
      if (res.ok) {
        const projects = await res.json();
        existingSelect.innerHTML = `<option value="">-- ${getI18n().label_select_project || "Select Project"} --</option>`;
        projects.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = `#${p.id} - ${p.name}`;
          existingSelect.appendChild(opt);
        });
        _projectsLoaded = true;
      }
    } catch (e) {
      console.error("Failed to load projects", e);
    }
  }

  // Target radio toggle
  targetNewRadio.addEventListener("change", () => {
    if (targetNewRadio.checked) {
      newFields.style.display = "block";
      existingFields.style.display = "none";
    }
  });

  targetExistingRadio.addEventListener("change", () => {
    if (targetExistingRadio.checked) {
      newFields.style.display = "none";
      existingFields.style.display = "block";
      loadExistingProjects();
    }
  });

  // Global helper to open import modal
  window.openBomImportModal = function (preselectProjectId = null) {
    _preselectedProjectId = preselectProjectId;
    resetModal();

    if (_preselectedProjectId) {
      targetExistingRadio.checked = true;
      newFields.style.display = "none";
      existingFields.style.display = "block";
      loadExistingProjects().then(() => {
        existingSelect.value = String(_preselectedProjectId);
        existingSelect.disabled = true; // Lock when opened from project details
      });
    } else {
      targetNewRadio.checked = true;
      newFields.style.display = "block";
      existingFields.style.display = "none";
      existingSelect.disabled = false;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  };

  function resetModal() {
    _parsedData = null;
    stage1.style.display = "block";
    stage2.style.display = "none";
    btnParse.style.display = "inline-block";
    btnBack.style.display = "none";
    btnConfirm.style.display = "none";
    btnParse.disabled = false;
    fileInput.value = "";
    projectNameInput.value = "";
    projectDescInput.value = "";
    tbody.innerHTML = "";
  }

  // Parse & Preview button
  btnParse.addEventListener("click", async () => {
    const file = fileInput.files[0];
    if (!file) {
      alert(getI18n().upload_label || "Please select a BOM file.");
      return;
    }

    // Validation
    if (targetNewRadio.checked && !projectNameInput.value.trim()) {
      // Suggest project name from filename
      let base = file.name.replace(/\.[^/.]+$/, "");
      base = base.replace(/^[bB][oO][mM]_+/, "");
      projectNameInput.value = base || "New BOM Project";
    } else if (targetExistingRadio.checked && !existingSelect.value) {
      alert(getI18n().label_select_project || "Please select an existing project.");
      return;
    }

    btnParse.disabled = true;
    btnParse.textContent = getI18n().parsing_bom || "Parsing BOM...";

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/projects/bom/preview", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to parse BOM file");
      }

      _parsedData = await res.json();
      if (!projectNameInput.value.trim() && _parsedData.suggested_project_name) {
        projectNameInput.value = _parsedData.suggested_project_name;
      }

      renderPreviewStage();
    } catch (e) {
      alert(e.message);
      btnParse.disabled = false;
      btnParse.textContent = getI18n().btn_parse_preview || "Parse & Preview";
    }
  });

  // Switch to Stage 2
  function renderPreviewStage() {
    stage1.style.display = "none";
    stage2.style.display = "block";
    btnParse.style.display = "none";
    btnBack.style.display = "inline-block";
    btnConfirm.style.display = "inline-block";

    updateSummaryCounters();

    // Target text
    if (targetNewRadio.checked) {
      targetSummaryText.textContent = `Target: [New Project] ${projectNameInput.value.trim()}`;
    } else {
      const opt = existingSelect.options[existingSelect.selectedIndex];
      targetSummaryText.textContent = `Target: [Existing Project] ${opt ? opt.text : ""}`;
    }

    renderTableRows();
  }

  // Back button
  btnBack.addEventListener("click", () => {
    stage1.style.display = "block";
    stage2.style.display = "none";
    btnParse.style.display = "inline-block";
    btnBack.style.display = "none";
    btnConfirm.style.display = "none";
    btnParse.disabled = false;
    btnParse.textContent = getI18n().btn_parse_preview || "Parse & Preview";
  });

  function updateSummaryCounters() {
    if (!_parsedData) return;
    let total = _parsedData.items.length;
    let inInv = 0;
    let matchedLib = 0;
    let unmatched = 0;

    _parsedData.items.forEach((item) => {
      if (item.status === "in_inventory") inInv++;
      else if (item.status === "matched_library" || item.is_custom) matchedLib++;
      else unmatched++;
    });

    summaryTotal.textContent = total;
    summaryInInv.textContent = inInv;
    summaryMatchedLib.textContent = matchedLib;
    summaryUnmatched.textContent = unmatched;
    const omitted = _parsedData.items.filter((item) => !item.selected).length;
    skippedSummary.textContent = (getI18n().skipped_rows_notice || "Rows not included: {count}")
      .replace("{count}", String(omitted));
    const bindable = _parsedData.items.filter((item) => item.status !== "unmatched" || item.is_custom);
    const chosen = bindable.filter((item) => item.selected).length;
    selectAllCb.checked = bindable.length > 0 && chosen === bindable.length;
    selectAllCb.indeterminate = chosen > 0 && chosen < bindable.length;
  }

  function renderTableRows() {
    tbody.innerHTML = "";
    if (!_parsedData || !_parsedData.items.length) return;

    _parsedData.items.forEach((item, idx) => {
      const tr = document.createElement("tr");
      tr.id = `bom-row-${idx}`;

      let statusBadge = "";
      let matchedInfoHtml = "";

      if (item.status === "in_inventory") {
        statusBadge = `<span class="badge bg-success">${getI18n().status_in_inventory || "In Inventory"}</span>`;
        matchedInfoHtml = `
          <div class="small">
            <strong class="text-dark">${escapeHtml(item.matched_part_name || "-")}</strong>
            <span class="text-muted ms-1">(${escapeHtml(item.matched_manufacturer || "-")})</span>
            <span class="badge bg-light text-dark border ms-1">Stock: ${item.inventory_quantity || 0}</span>
          </div>
        `;
      } else if (item.is_custom) {
        statusBadge = `<span class="badge bg-info text-dark">Custom Part</span>`;
        matchedInfoHtml = `
          <div class="small d-flex justify-content-between align-items-center">
            <div>
              <strong class="text-primary">${escapeHtml(item.custom_name)}</strong>
              <span class="text-muted ms-1">(${escapeHtml(item.custom_manufacturer)})</span>
            </div>
            <button type="button" class="btn btn-outline-secondary btn-sm py-0 px-1" onclick="window.editCustomRow(${idx})">Edit</button>
          </div>
        `;
      } else if (item.status === "matched_library") {
        const libName = librarySourceName(item.library_source);
        statusBadge = `<span class="badge bg-primary">${getI18n().status_matched_library || "Library Match"}</span>`;
        matchedInfoHtml = `
          <div class="small">
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <span class="badge bg-dark me-1">${libName}</span>
                <strong class="text-dark">${escapeHtml(item.matched_part_name || "-")}</strong>
              </div>
              <button type="button" class="btn btn-outline-secondary btn-sm py-0 px-1" onclick="window.openSearchBindModal(${idx})">Rebind</button>
            </div>
            ${(item.conflicts || []).length ? `<div class="small text-danger">${escapeHtml(item.conflicts.map((name) => getI18n()[`conflict_${name}`] || name).join("; "))}</div>` : ""}
            <div class="form-check mt-1 mb-0">
              <input class="form-check-input row-zero-stock-cb" type="checkbox" id="cb-zero-${idx}" ${item.auto_create_zero_stock ? "checked" : ""}>
              <label class="form-check-label text-muted" style="font-size: 0.75rem;" for="cb-zero-${idx}">
                ${getI18n().auto_create_zero_stock_hint || "Auto create 0-stock record"}
              </label>
            </div>
          </div>
        `;
      } else {
        const review = (item.conflicts || []).length || (item.suggestions || []).length;
        statusBadge = `<span class="badge bg-warning text-dark">${review ? (getI18n().status_review_required || "Review required") : (getI18n().status_unmatched || "Unmatched")}</span>`;
        const reason = getI18n()[`reason_${item.match_reason}`] || item.match_reason || "";
        const conflicts = (item.conflicts || []).map((name) => getI18n()[`conflict_${name}`] || name);
        const missingDimensions = (item.missing_dimensions || []).map((name) => getI18n()[`dimension_${name}`] || name);
        const suggestions = (item.suggestions || []).slice(0, 3).map((candidate, candidateIndex) => `
          <div class="d-flex justify-content-between align-items-center small border-top py-1 gap-2">
            <span class="text-truncate">
              <strong>${escapeHtml(librarySourceName(candidate.library_source))}</strong>
              ${escapeHtml(candidate.name)}
              <span class="text-muted">${escapeHtml([candidate.value, candidate.package, candidate.voltage, candidate.tolerance].filter(Boolean).join(" | "))}</span>
            </span>
            <button type="button" class="btn btn-outline-primary btn-sm row-suggestion-btn" data-idx="${idx}" data-candidate="${candidateIndex}">${getI18n().btn_select_part || "Select"}</button>
          </div>
        `).join("");
        matchedInfoHtml = `
          <div class="small text-muted">${escapeHtml(reason)}</div>
          ${missingDimensions.length ? `<div class="small text-muted">${escapeHtml(getI18n().missing_dimensions_prefix || "Missing dimensions")}: ${escapeHtml(missingDimensions.join(", "))}</div>` : ""}
          ${conflicts.length ? `<div class="small text-danger">${escapeHtml(conflicts.join("; "))}</div>` : ""}
          ${suggestions ? `<div class="small text-muted mt-1">${getI18n().suggested_candidates || "Candidates"}</div>${suggestions}` : ""}
          <div class="d-flex gap-1 align-items-center mt-1">
            <button type="button" class="btn btn-outline-primary btn-sm py-0 px-2" onclick="window.openSearchBindModal(${idx})">
              ${getI18n().btn_search_bind || "Search"}
            </button>
            <button type="button" class="btn btn-outline-dark btn-sm py-0 px-2" onclick="window.openCustomPartModal(${idx})">
              ${getI18n().btn_create_custom || "New Part"}
            </button>
          </div>
        `;
      }

      tr.innerHTML = `
        <td class="text-center">
          <input class="form-check-input row-select-cb" type="checkbox" data-idx="${idx}" ${item.selected ? "checked" : ""} ${item.status === "unmatched" && !item.is_custom ? "disabled" : ""}>
        </td>
        <td class="text-muted small">${item.row_index}</td>
        <td>
          <div class="fw-bold text-dark">${escapeHtml(item.value || item.comment || item.manufacturer_part || "-")}</div>
          ${item.value && item.comment && item.value !== item.comment ? `<small class="d-block text-muted">${getI18n().label_comment || "Comment"}: ${escapeHtml(item.comment)}</small>` : ""}
          ${item.manufacturer_part && item.manufacturer_part !== item.value && item.manufacturer_part !== item.comment ? `<small class="d-block text-muted">${escapeHtml(item.manufacturer_part)}</small>` : ""}
          <small class="text-muted">${escapeHtml(item.manufacturer || "")}</small>
        </td>
        <td><code>${escapeHtml(item.designator || "-")}</code></td>
        <td><code>${escapeHtml(item.footprint || "-")}</code></td>
        <td>
          <input type="number" min="1" class="form-control form-control-sm text-center row-qty-input" data-idx="${idx}" value="${item.quantity}" style="width: 70px;">
        </td>
        <td>${statusBadge}</td>
        <td>${matchedInfoHtml}</td>
      `;

      tbody.appendChild(tr);
    });

    // Attach listeners
    tbody.querySelectorAll(".row-select-cb").forEach((cb) => {
      cb.addEventListener("change", function () {
        const i = parseInt(this.getAttribute("data-idx"), 10);
        _parsedData.items[i].selected = this.checked;
        updateSummaryCounters();
      });
    });

    tbody.querySelectorAll(".row-qty-input").forEach((inp) => {
      inp.addEventListener("change", function () {
        const i = parseInt(this.getAttribute("data-idx"), 10);
        _parsedData.items[i].quantity = Math.max(1, parseInt(this.value, 10) || 1);
      });
    });

    tbody.querySelectorAll(".row-zero-stock-cb").forEach((cb) => {
      cb.addEventListener("change", function () {
        const i = parseInt(this.id.replace("cb-zero-", ""), 10);
        _parsedData.items[i].auto_create_zero_stock = this.checked;
      });
    });
    tbody.querySelectorAll(".row-suggestion-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.idx);
        const candidate = _parsedData.items[index].suggestions[Number(button.dataset.candidate)];
        selectCandidate(index, candidate);
      });
    });
  }

  // Select all checkbox
  selectAllCb.addEventListener("change", function () {
    const isChecked = this.checked;
    if (_parsedData) {
      _parsedData.items.forEach((item) => {
        item.selected = isChecked && (item.status !== "unmatched" || item.is_custom);
      });
    }
    tbody.querySelectorAll(".row-select-cb").forEach((cb) => (cb.checked = isChecked && !cb.disabled));
    updateSummaryCounters();
  });

  // Search & Bind Modal Logic
  window.openSearchBindModal = function (rowIndex) {
    _currentBindingRowIndex = rowIndex;
    const item = _parsedData.items[rowIndex];
    bindSearchInput.value = item.raw_supplier_part || item.manufacturer_part || item.value || item.comment || "";
    renderBindSearchResults({ items: item.suggestions || [] });

    const modal = bootstrap.Modal.getOrCreateInstance(searchModalEl);
    modal.show();

    if (bindSearchInput.value.trim() && !(item.suggestions || []).length) {
      executeBindSearch();
    }
  };

  bindSearchBtn.addEventListener("click", executeBindSearch);
  bindSearchInput.addEventListener("keyup", (e) => {
    if (e.key === "Enter") executeBindSearch();
  });

  async function executeBindSearch() {
    const query = (bindSearchInput.value || "").trim();
    if (!query) return;

    bindSearchResults.innerHTML = `<div class="text-muted text-center py-3">${getI18n().searching || "Searching libraries..."}</div>`;
    try {
      const res = await fetch("/api/projects/bom/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item: _parsedData.items[_currentBindingRowIndex], query }),
      });
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      renderBindSearchResults(data);
    } catch (e) {
      bindSearchResults.innerHTML = `<div class="text-danger text-center py-2">${e.message}</div>`;
    }
  }

  function renderBindSearchResults(data) {
    bindSearchResults.innerHTML = "";
    const items = data.items || [];

    if (items.length === 0) {
      bindSearchResults.innerHTML = `<div class="text-muted text-center py-4">${getI18n().no_matches || "No matching components found."}</div>`;
      return;
    }

    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "p-2 border-bottom bg-white d-flex justify-content-between align-items-center";

      const sourceName = librarySourceName(it.library_source);
      const meta = [it.lcsc_part, it.value, it.package, it.voltage, it.tolerance, it.manufacturer,
        `${getI18n().stock_label || "Stock"}: ${(it.stock || 0).toLocaleString()}`].filter(Boolean).join(" | ");
      const conflicts = (it.conflicts || []).map((name) => getI18n()[`conflict_${name}`] || name).join("; ");

      row.innerHTML = `
        <div class="me-2 text-truncate">
          <div class="d-flex align-items-center gap-1">
            <span class="badge bg-dark">${escapeHtml(sourceName)}</span>
            <strong class="text-dark">${escapeHtml(it.name)}</strong>
          </div>
          <small class="text-muted d-block text-truncate">${escapeHtml(meta)}</small>
          ${conflicts ? `<small class="text-danger d-block">${escapeHtml(conflicts)}</small>` : ""}
        </div>
        <button type="button" class="btn btn-outline-primary btn-sm text-nowrap">
          ${getI18n().btn_select_part || "Select"}
        </button>
      `;

      row.querySelector("button").addEventListener("click", () => {
        if (selectCandidate(_currentBindingRowIndex, it)) {
          bootstrap.Modal.getInstance(searchModalEl).hide();
        }
      });

      bindSearchResults.appendChild(row);
    });
  }

  function bindingFromCandidate(candidate) {
    return {
      library_source: candidate.library_source,
      external_part_id: candidate.external_part_id,
      matched_part_name: candidate.name,
      matched_manufacturer: candidate.manufacturer || "",
      matched_package: candidate.package || "",
      matched_stock: candidate.stock || 0,
      status: "matched_library",
      auto_create_zero_stock: true,
      is_custom: false,
      inventory_part_id: null,
      selected: true,
      confirmed_match: true,
      match_reason: "manual_selection",
      conflicts: candidate.conflicts || [],
    };
  }

  function selectCandidate(rowIndex, candidate) {
    const conflicts = [...new Set([...(_parsedData.items[rowIndex].conflicts || []), ...(candidate.conflicts || [])])];
    if (conflicts.length && !window.confirm(getI18n().confirm_conflicting_candidate || "This candidate conflicts with the BOM. Bind it anyway?")) {
      return false;
    }
    bindComponentToRow(rowIndex, { ...bindingFromCandidate(candidate), conflicts });
    return true;
  }

  function bindComponentToRow(rowIndex, bindData) {
    if (rowIndex === null || !_parsedData) return;
    Object.assign(_parsedData.items[rowIndex], bindData);
    if (bindData.status === "matched_library" || bindData.is_custom) {
      _parsedData.items[rowIndex].selected = true;
      _parsedData.items[rowIndex].confirmed_match = true;
    }
    updateSummaryCounters();
    renderTableRows();
  }

  // Custom Part Modal Logic
  window.openCustomPartModal = function (rowIndex) {
    _currentBindingRowIndex = rowIndex;
    const item = _parsedData.items[rowIndex];
    customNameInput.value = item.comment || item.manufacturer_part || "";
    customMfrInput.value = item.manufacturer || "Generic";
    customPkgInput.value = item.footprint || "Standard";
    customDescInput.value = `Imported from BOM: ${item.designator || ""}`;

    const modal = bootstrap.Modal.getOrCreateInstance(customModalEl);
    modal.show();
  };

  window.editCustomRow = function (rowIndex) {
    window.openCustomPartModal(rowIndex);
  };

  btnSaveCustom.addEventListener("click", () => {
    const name = customNameInput.value.trim();
    if (!name) {
      alert("Part name is required");
      return;
    }

    bindComponentToRow(_currentBindingRowIndex, {
      is_custom: true,
      custom_name: name,
      custom_manufacturer: customMfrInput.value.trim() || "Generic",
      custom_package: customPkgInput.value.trim() || "Standard",
      custom_description: customDescInput.value.trim(),
      status: "matched_library",
      matched_part_name: name,
      matched_manufacturer: customMfrInput.value.trim(),
      library_source: "custom",
      selected: true,
      confirmed_match: true,
    });

    bootstrap.Modal.getInstance(customModalEl).hide();
  });

  // Confirm Import
  btnConfirm.addEventListener("click", async () => {
    const selectedItems = (_parsedData ? _parsedData.items : []).filter((it) => it.selected);
    if (!selectedItems.length) {
      alert(getI18n().no_items_selected || "Please select at least one component to import.");
      return;
    }
    const omitted = _parsedData.items.length - selectedItems.length;
    if (omitted && !window.confirm((getI18n().skipped_confirm || "{count} BOM rows will not be imported. Continue?")
      .replace("{count}", String(omitted)))) return;

    const targetType = targetNewRadio.checked ? "new" : "existing";
    const projectName = projectNameInput.value.trim();
    const projectDesc = projectDescInput.value.trim();
    const existingProjectId = targetExistingRadio.checked ? parseInt(existingSelect.value, 10) : null;
    const qtyStrategy = document.querySelector('input[name="bomQuantityStrategy"]:checked')?.value || "overwrite";

    if (targetType === "new" && !projectName) {
      alert(getI18n().label_project_name || "Project name is required.");
      return;
    }
    if (targetType === "existing" && !existingProjectId) {
      alert(getI18n().label_select_project || "Please select an existing project.");
      return;
    }

    btnConfirm.disabled = true;
    btnConfirm.textContent = getI18n().importing || "Importing...";

    const payload = {
      target_type: targetType,
      project_name: projectName,
      project_description: projectDesc,
      existing_project_id: existingProjectId,
      quantity_strategy: qtyStrategy,
      items: selectedItems,
    };

    try {
      const res = await fetch("/api/projects/bom/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Import failed");
      }

      const result = await res.json();
      alert(getI18n().import_success || "BOM imported successfully!");
      window.location.href = `/project_details?project_id=${result.project_id}`;
    } catch (e) {
      alert(e.message);
      btnConfirm.disabled = false;
      btnConfirm.textContent = getI18n().btn_confirm_import || "Confirm Import";
    }
  });
})();
