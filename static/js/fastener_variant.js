(() => {
  function canonicalDecimal(value) {
    const [rawInteger, rawFraction = ""] = String(value).split(".");
    const integer = rawInteger.replace(/^0+(?=\d)/, "") || "0";
    const fraction = rawFraction.replace(/0+$/, "");
    return fraction ? `${integer}.${fraction}` : integer;
  }

  function normalizeNominal(value) {
    const text = String(value || "").trim().replace(/\s+/g, "").toUpperCase();
    const metric = text.match(/^M(\d+(?:\.\d+)?)$/);
    if (metric) return `M${canonicalDecimal(metric[1])}`;
    const inch = text.match(/^(\d+\/\d+)(?:IN|INCH|")?$/);
    if (inch) return `${inch[1]}in`;
    return text;
  }

  function normalizeLength(value) {
    const text = String(value || "").trim().replace(/\s+/g, "").toLowerCase();
    if (!text) return "";
    const inch = text.match(/^(\d+(?:\.\d+)?|\d+\/\d+)(?:inch|in|")$/);
    if (inch) return `${inch[1]}in`;
    const metric = text.match(/^(\d+(?:\.\d+)?)(?:mm)?$/);
    if (metric) return canonicalDecimal(metric[1]);
    return text.toUpperCase();
  }

  function encode(value) {
    return encodeURIComponent(String(value || "")).replace(/[!'()*]/g, character =>
      `%${character.charCodeAt(0).toString(16).toUpperCase()}`
    );
  }

  window.buildFastenerVariantId = function (standardCode, nominal, length) {
    const code = String(standardCode || "").trim();
    const size = normalizeNominal(nominal);
    const lengthKey = normalizeLength(length) || "-";
    return `fastener:v1/${encode(code)}/${encode(size)}/${encode(lengthKey)}`;
  };

  window.buildCustomFastenerVariantId = function (standardCode, rowKey) {
    const code = String(standardCode || '').trim();
    const key = String(rowKey || '').trim();
    if (!code || !key.startsWith('user:')) {
      throw new Error('A custom fastener parameter row is required');
    }
    return `fastener:v2/${encode(code)}/${encode(key)}`;
  };
})();
