(function (root) {
  "use strict";
  function parse(raw) {
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
    if (!/^C\d{3,10}$/i.test(result.pc || "") || !(result.pm || "").trim()) throw new Error("Missing component");
    if (!/^\d+$/.test(result.qty || "") || !(Number(result.qty) > 0) || Number(result.qty) > 2147483647) throw new Error("Invalid quantity");
    result.pc = `C${Number(result.pc.slice(1))}`;
    result.qty = Number(result.qty);
    return result;
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
  const api = {parse, projectChoice, requestId, repeatCameraScan};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ScanLabel = api;
})(globalThis);
