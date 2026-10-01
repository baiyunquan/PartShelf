(() => {
  "use strict";
  const I18N = JSON.parse(document.getElementById("page-translations").textContent);
  const source = document.getElementById("selectedSource");
  const externalId = document.getElementById("selectedExtId");
  const quantity = document.getElementById("inputQuantity");
  const type = document.getElementById("inventory-drawer-type");
  const panel = document.getElementById("inventory-recommendation");
  const message = document.getElementById("inventory-recommendation-message");
  const notice = document.getElementById("inventory-placement-notice");
  let requestVersion = 0;
  let recommended = null;
  type.value = "S";

  function setMessage(key, error = false) {
    message.textContent = I18N[key] || key;
    message.classList.toggle("text-danger", error);
  }
  function snapshot() {
    return {library_source: source.value, external_part_id: externalId.value,
      drawer_type: type.value || "S", recommended};
  }
  window.InventoryRecommendation = {snapshot};

  async function refresh() {
    const version = ++requestVersion;
    recommended = null;
    panel.hidden = !source.value || !externalId.value;
    if (panel.hidden) return;
    const amount = Number(quantity.value);
    if (!Number.isInteger(amount) || amount <= 0) {
      setMessage("placement_no_stock");
      return;
    }
    setMessage("placement_loading");
    const query = new URLSearchParams({library_source: source.value, external_part_id: externalId.value,
      quantity: String(amount), drawer_type: type.value || "S"});
    try {
      const response = await fetch(`/api/warehouse/suggestion?${query}`);
      if (!response.ok) throw new Error("Warehouse preview failed");
      const result = await response.json();
      if (version !== requestVersion) return;
      recommended = result.recommended;
      if (recommended) {
        message.textContent = `${recommended.cabinet_id} / ${recommended.drawer_code} — ${I18N[`placement_${result.reason}`] || result.reason}`;
        message.classList.toggle("text-danger", false);
      } else setMessage(`placement_${result.reason}`, true);
    } catch (error) {
      if (version === requestVersion) setMessage("placement_error", true);
    }
  }

  document.addEventListener("inventory:component-selected", refresh);
  type.addEventListener("change", refresh);
  quantity.addEventListener("input", refresh);
  document.getElementById("addPartInventoryForm").addEventListener("reset", () => {
    ++requestVersion;
    recommended = null;
    type.value = "S";
    panel.hidden = true;
  });
  document.addEventListener("inventory:added", event => {
    const {part, recommendation} = event.detail;
    notice.hidden = true;
    if (!(part.quantity > 0)) return;
    const context = recommendation || {drawer_type: "S"};
    const params = new URLSearchParams({part_id: String(part.id), drawer_type: context.drawer_type || "S"});
    const target = context.recommended;
    if (target && context.library_source === part.library_source && String(context.external_part_id) === String(part.external_part_id)) {
      params.set("cabinet_id", target.cabinet_id);
      params.set("drawer_code", target.drawer_code);
    }
    document.getElementById("inventory-placement-continue").href = `/warehouse?${params}`;
    document.getElementById("inventory-placement-notice-text").textContent =
      (I18N.warehouse_added || "Inventory added: {name}. ").replace("{name}", part.name || `#${part.id}`);
    notice.hidden = false;
  });
})();
