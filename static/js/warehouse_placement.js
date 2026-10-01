(() => {
  "use strict";
  const I18N = JSON.parse(document.getElementById("page-translations").textContent);
  const form = document.getElementById("warehouse-placement-form");
  const partSelect = document.getElementById("warehouse-part-select");
  const typeSelect = document.getElementById("warehouse-drawer-type");
  const pageParams = new URLSearchParams(window.location.search);
  const initialPartId = pageParams.get("part_id") || "";
  const initialType = pageParams.get("drawer_type") === "L" ? "L" : "S";
  typeSelect.value = initialType;
  let preferredTarget = pageParams.get("cabinet_id") && pageParams.get("drawer_code") ? {
    cabinet_id: pageParams.get("cabinet_id"), drawer_code: pageParams.get("drawer_code"),
  } : null;
  const targetSelect = document.getElementById("warehouse-placement-target");
  const photo = document.getElementById("warehouse-photo");
  const preview = document.getElementById("warehouse-photo-preview");
  const message = document.getElementById("warehouse-placement-message");
  const confirmButton = document.getElementById("warehouse-placement-confirm");
  const search = document.getElementById("warehouse-part-search");
  let candidates = [];
  let suggestionVersion = 0;
  let searchVersion = 0;
  let photoUrl;
  let saving = false;

  function text(key) { return I18N[key] || key; }
  function option(value, label) { return new Option(label, value); }
  function showMessage(key, error = false) {
    message.textContent = text(key);
    message.classList.toggle("text-danger", error);
  }
  function updateButton() {
    confirmButton.disabled = saving || !partSelect.value || targetSelect.disabled || !targetSelect.value || !photo.files.length;
  }
  function showTarget() {
    const target = candidates[Number(targetSelect.value)];
    if (target && targetSelect.value !== "") {
      document.dispatchEvent(new CustomEvent("warehouse:show-drawer", { detail: target }));
    }
  }
  function resetSuggestion() {
    candidates = [];
    targetSelect.replaceChildren();
    targetSelect.disabled = true;
    updateButton();
  }
  async function request(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
      const error = new Error("Warehouse request failed");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  async function suggest() {
    const version = ++suggestionVersion;
    resetSuggestion();
    if (!partSelect.value || !typeSelect.value) {
      showMessage(partSelect.children.length <= 1 ? "placement_no_parts" : "choose_part_type");
      return;
    }
    showMessage("placement_loading");
    try {
      const result = await request(`/api/warehouse/parts/${encodeURIComponent(partSelect.value)}/suggestion?drawer_type=${typeSelect.value}`);
      if (version !== suggestionVersion) return;
      candidates = result.candidates;
      for (const [index, target] of candidates.entries()) {
        targetSelect.add(option(String(index), `${target.cabinet_id} / ${target.drawer_code} — ${text(`placement_${target.state}`)}`));
      }
      targetSelect.disabled = candidates.length === 0;
      if (candidates.length) {
        const prefer = preferredTarget && partSelect.value === initialPartId && typeSelect.value === initialType;
        const preferredIndex = prefer ? candidates.findIndex(target =>
          target.cabinet_id === preferredTarget.cabinet_id && target.drawer_code === preferredTarget.drawer_code) : -1;
        targetSelect.value = String(preferredIndex >= 0 ? preferredIndex : 0);
        message.textContent = `${text("placement_group")}: ${result.group.label}. ${text(`placement_${result.reason}`)}`;
        if (prefer && preferredIndex < 0) message.textContent += ` ${text("placement_target_changed")}`;
        preferredTarget = null;
        showTarget();
      } else {
        showMessage(`placement_${result.reason}`, true);
        if (result.placement) document.dispatchEvent(new CustomEvent("warehouse:show-drawer", {detail: result.placement}));
      }
      updateButton();
    } catch (error) {
      if (version === suggestionVersion) showMessage("placement_error", true);
    }
  }
  async function loadParts(preselect = "") {
    const version = ++searchVersion;
    ++suggestionVersion;
    resetSuggestion();
    const query = search.value.trim();
    const url = query ? `/api/inventory/search?search_key=${encodeURIComponent(query)}&warehouse_status=not_in_warehouse`
      : "/api/inventory/get_parts_inventory?warehouse_status=not_in_warehouse";
    try {
      const parts = await request(url);
      if (preselect && !parts.some(part => String(part.id) === preselect)) {
        parts.unshift(await request(`/api/inventory/get_part_by_id?part_id=${encodeURIComponent(preselect)}`));
      }
      if (version !== searchVersion) return;
      const selectedPart = parts.find(item => String(item.id) === preselect);
      if (selectedPart && selectedPart.warehouse_status === "in_warehouse") {
        document.dispatchEvent(new CustomEvent("warehouse:show-drawer", {detail: {
          cabinet_id: selectedPart.warehouse_box_id, drawer_code: selectedPart.warehouse_drawer_code,
        }}));
      }
      partSelect.replaceChildren(option("", text("choose_part")));
      for (const part of parts.filter(item => item.quantity > 0 || String(item.id) === preselect)) {
        partSelect.add(option(String(part.id), `#${part.id} ${part.name} · ${part.package || ""} · ${text("part_quantity")}: ${part.quantity}`));
      }
      partSelect.value = preselect;
      if (!partSelect.value) partSelect.value = "";
      await suggest();
    } catch (error) {
      if (version === searchVersion) showMessage("placement_error", true);
    }
  }
  partSelect.addEventListener("change", () => { preferredTarget = null; suggest(); });
  typeSelect.addEventListener("change", () => { preferredTarget = null; suggest(); });
  targetSelect.addEventListener("change", showTarget);
  photo.addEventListener("change", () => {
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = photo.files.length ? URL.createObjectURL(photo.files[0]) : undefined;
    preview.hidden = !photoUrl;
    if (photoUrl) preview.src = photoUrl;
    else preview.removeAttribute("src");
    updateButton();
  });
  document.getElementById("warehouse-part-search-button").addEventListener("click", () => loadParts());
  search.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); loadParts(); }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (confirmButton.disabled || !form.reportValidity()) return;
    const target = candidates[Number(targetSelect.value)];
    const partId = partSelect.value;
    const body = new FormData();
    body.append("cabinet_id", target.cabinet_id);
    body.append("drawer_code", target.drawer_code);
    body.append("photo", photo.files[0]);
    saving = true;
    updateButton();
    Array.from(form.elements).forEach(element => { element.disabled = true; });
    try {
      await request(`/api/warehouse/parts/${encodeURIComponent(partId)}/placement`, { method: "POST", body });
      photo.value = "";
      photo.dispatchEvent(new Event("change"));
      document.dispatchEvent(new Event("warehouse:refresh"));
      await loadParts();
      showMessage("placement_saved");
    } catch (error) {
      await suggest();
      showMessage(error.status === 409 ? "placement_conflict" : "placement_upload_error", true);
    } finally {
      saving = false;
      Array.from(form.elements).forEach(element => { element.disabled = false; });
      targetSelect.disabled = candidates.length === 0;
      updateButton();
    }
  });
  document.getElementById("warehouse-drawer-parts").addEventListener("click", async event => {
    const button = event.target.closest("[data-remove-part-id]");
    if (!button || !window.confirm(text("remove_confirm"))) return;
    button.disabled = true;
    try {
      await request(`/api/warehouse/parts/${encodeURIComponent(button.dataset.removePartId)}/placement`, {method: "DELETE"});
      document.dispatchEvent(new Event("warehouse:refresh"));
      await loadParts(partSelect.value === button.dataset.removePartId ? button.dataset.removePartId : "");
      showMessage("placement_removed");
    } catch (error) {
      button.disabled = false;
      showMessage("placement_error", true);
    }
  });
  loadParts(initialPartId);
})();
