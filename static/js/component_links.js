(function (root) {
  "use strict";

  function numericId(value) {
    const text = String(value ?? "").replace(/^0+(?=\d)/, "");
    return /^[1-9]\d*$/.test(text) ? text : null;
  }

  function detailUrl(part) {
    const inventoryId = numericId(part.part_id || part.inventory_part_id);
    if (inventoryId) return `/component_details?part_id=${inventoryId}`;
    const source = part.library_source || part._source;
    if (source === "fasteners") {
      let code = part.standard_code;
      if (!code && part.external_part_id) {
        const identity = String(part.external_part_id);
        if (/^fastener:v[12]\//.test(identity)) {
          try { code = decodeURIComponent(identity.split("/")[1]); }
          catch (error) { return null; }
        } else code = identity;
      }
      return code ? `/libraries/fasteners/${encodeURIComponent(code)}` : null;
    }
    if (!["jlcparts", "altium", "kicad"].includes(source)) return null;
    const rawId = part.external_part_id ?? (source === "jlcparts" ? part.lcsc : part.id);
    const identity = numericId(source === "jlcparts" ? String(rawId ?? "").replace(/^[Cc]/, "") : rawId);
    return identity ? `/libraries/${source}/${identity}` : null;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function renderNameLink(part, name) {
    const url = detailUrl(part);
    const label = escapeHtml(name);
    return url ? `<a href="${escapeHtml(url)}" class="fw-bold text-decoration-none" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
  }

  const helpers = {detailUrl, renderNameLink};
  if (typeof module === "object" && module.exports) module.exports = helpers;
  else root.ComponentLinks = helpers;
})(typeof window === "undefined" ? globalThis : window);
