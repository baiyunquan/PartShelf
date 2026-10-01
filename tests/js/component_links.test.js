const test = require("node:test");
const assert = require("node:assert/strict");
const {detailUrl, renderNameLink} = require("../../static/js/component_links.js");

test("links catalog and inventory identifiers to their correct detail pages", () => {
  for (const [part, expected] of [
    [{library_source: "jlcparts", external_part_id: "C123"}, "/libraries/jlcparts/123"],
    [{_source: "jlcparts", lcsc: 123}, "/libraries/jlcparts/123"],
    [{library_source: "altium", external_part_id: "42"}, "/libraries/altium/42"],
    [{_source: "kicad", id: 8}, "/libraries/kicad/8"],
    [{part_id: 9}, "/component_details?part_id=9"],
    [{library_source: "fasteners", external_part_id: "fastener:v1/DIN%20912/M3/8"}, "/libraries/fasteners/DIN%20912"],
    [{library_source: "fasteners", external_part_id: "fastener:v2/DIN%20912/user%3A1"}, "/libraries/fasteners/DIN%20912"],
    [{_source: "fasteners", standard_code: "DIN 912"}, "/libraries/fasteners/DIN%20912"],
  ]) assert.equal(detailUrl(part), expected);
});

test("unknown or unsaved components have no fabricated detail link", () => {
  for (const part of [{}, {library_source: "custom", external_part_id: "5"},
    {library_source: "jlcparts", external_part_id: "not-an-id"},
    {library_source: "fasteners", external_part_id: "fastener:v1/%ZZ/M3/8"}]) {
    assert.equal(detailUrl(part), null);
    assert.equal(renderNameLink(part, "<Part>"), "&lt;Part&gt;");
  }
});

test("names are escaped and detail links open separately from the selection action", () => {
  const markup = renderNameLink({part_id: 7}, '<script>"model"</script>');
  assert.ok(markup.includes('href="/component_details?part_id=7"'));
  assert.ok(markup.includes('target="_blank"'));
  assert.ok(markup.includes('rel="noopener noreferrer"'));
  assert.ok(markup.includes("&lt;script&gt;&quot;model&quot;&lt;/script&gt;"));
  assert.ok(!markup.includes("onclick"));
});
