(function (root) {
  "use strict";
  function parse(raw, allowIncomplete = false) {
    if (typeof raw !== "string" || raw.length > 4096) throw new Error("Invalid label");
    const text = raw.trim();
    if (!text.startsWith("{") || !text.endsWith("}")) throw new Error("Invalid label");
    const body = text.slice(1, -1).trim();
    const keys = Array.from(body.matchAll(/(?:^|,)\s*([a-z][a-z0-9_]*)\s*:/gi));
    const result = Object.create(null);
    if (!keys.length || keys[0].index !== 0) throw new Error("Invalid label");
    for (const [index, match] of keys.entries()) {
      const key = match[1].toLowerCase();
      if (Object.hasOwn(result, key)) throw new Error("Duplicate label field");
      const end = index + 1 < keys.length ? keys[index + 1].index : body.length;
      result[key] = body.slice(match.index + match[0].length, end).trim();
      if (/[{},]/.test(result[key])) throw new Error("Invalid label value");
    }
    if (!/^C\d{3,10}$/i.test(result.pc || "") || (!allowIncomplete && !(result.pm || "").trim())) throw new Error("Missing component");
    const validQuantity = /^\d+$/.test(result.qty || "") && Number(result.qty) > 0 && Number(result.qty) <= 2147483647;
    if (!validQuantity && !allowIncomplete) throw new Error("Invalid quantity");
    result.pc = `C${Number(result.pc.slice(1))}`;
    result.pm = result.pm || "";
    result.qty = validQuantity ? Number(result.qty) : null;
    return result;
  }
  function decodeChoice(results) {
    const labels = new Map();
    for (const result of results) {
      try {
        const parsed = parse(result.text, true);
        labels.set(JSON.stringify(parsed), {raw: result.text, label: parsed});
      } catch (_error) { /* Ordinary barcode or unsupported QR. */ }
    }
    const valid = [...labels.values()];
    if (valid.length > 1) return {kind: "multiple", qr_texts: valid.map(item => item.raw)};
    if (valid.length === 1) return {kind: "jlc", qr_text: valid[0].raw, label: valid[0].label};
    return {kind: "ordinary", qr_text: results[0]?.text || ""};
  }
  function confirmationIdentity(code, selected) {
    if (selected && selected.library_source && selected.external_part_id) {
      const expected = selected.library_source === "jlcparts" ? `C${selected.external_part_id}` : String(selected.external_part_id);
      if (code === expected) return {library_source: selected.library_source, external_part_id: String(selected.external_part_id)};
    }
    return {lcsc_code: code};
  }
  function projectChoice(projects, saved, token = null) {
    return projects.some(project => !project.is_system && String(project.id) === String(saved)
      && (token === null || project.identity_token === token)) ? String(saved) : "";
  }
  function repeatCameraScan(seen) {
    seen.clear();
  }
  function requestId() {
    if (root.crypto.randomUUID) return root.crypto.randomUUID();
    const bytes = root.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  const api = {parse, decodeChoice, confirmationIdentity, projectChoice, requestId, repeatCameraScan};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ScanLabel = api;
})(globalThis);
