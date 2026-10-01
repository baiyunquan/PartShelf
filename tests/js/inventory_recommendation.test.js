const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const script = fs.readFileSync("static/js/inventory_recommendation.js", "utf8");
const bundle = JSON.parse(fs.readFileSync("app/i18n/locales/en.json", "utf8"));
const I18N = {...bundle.warehouse, ...bundle.inventory};
const settle = () => new Promise(resolve => setImmediate(resolve));
class Element extends EventTarget {
  constructor(value = "") { super(); this.value = value; this.hidden = false; this.classList = {toggle() {}}; }
  removeAttribute() {}
}
class DetailEvent extends Event { constructor(type, detail) { super(type); this.detail = detail; } }

function setup({delayed = false, failure = false} = {}) {
  const ids = ["page-translations", "selectedSource", "selectedExtId", "inputQuantity", "inventory-drawer-type",
    "inventory-recommendation", "inventory-recommendation-message", "addPartInventoryForm",
    "inventory-placement-notice", "inventory-placement-notice-text", "inventory-placement-continue"];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  nodes["page-translations"].textContent = JSON.stringify(I18N);
  nodes.inputQuantity.value = "1";
  const document = new EventTarget();
  document.getElementById = id => nodes[id];
  const window = {};
  const calls = [], pending = [];
  const fetch = async url => {
    calls.push(url);
    const params = new URL(url, "http://localhost").searchParams;
    const code = params.get("drawer_type") === "L" ? "L-01" : "S-01";
    const response = {ok: !failure, json: async () => ({reason: "empty", recommended: {cabinet_id: "BOX-000", drawer_code: code}})};
    return delayed ? new Promise(resolve => pending.push(() => resolve(response))) : response;
  };
  vm.runInNewContext(script, {document, window, fetch, URLSearchParams, Event});
  function select(source, externalId) {
    nodes.selectedSource.value = source;
    nodes.selectedExtId.value = externalId;
    document.dispatchEvent(new Event("inventory:component-selected"));
  }
  return {nodes, window, document, calls, pending, select};
}

test("selecting a component previews a small drawer without creating inventory", async () => {
  const fixture = setup();
  fixture.select("altium", "10");
  await settle();
  const params = new URL(fixture.calls[0], "http://localhost").searchParams;
  assert.equal(params.get("drawer_type"), "S");
  assert.equal(params.get("quantity"), "1");
  assert.equal(params.get("external_part_id"), "10");
  assert.equal(fixture.nodes["inventory-recommendation"].hidden, false);
  assert.ok(fixture.nodes["inventory-recommendation-message"].textContent.includes("BOX-000 / S-01"));
  assert.equal(fixture.calls.length, 1);
});

test("stale recommendations cannot overwrite a new component or large drawer choice", async () => {
  const fixture = setup({delayed: true});
  fixture.select("altium", "10");
  fixture.nodes["inventory-drawer-type"].value = "L";
  fixture.select("altium", "11");
  fixture.pending[1]();
  await settle();
  fixture.pending[0]();
  await settle();
  assert.equal(fixture.window.InventoryRecommendation.snapshot().external_part_id, "11");
  assert.ok(fixture.nodes["inventory-recommendation-message"].textContent.includes("L-01"));
});

test("zero stock has no placement recommendation and reset restores small drawers", async () => {
  const fixture = setup();
  fixture.nodes.inputQuantity.value = "0";
  fixture.select("altium", "10");
  await settle();
  assert.equal(fixture.calls.length, 0);
  assert.equal(fixture.nodes["inventory-recommendation-message"].textContent, I18N.placement_no_stock);
  fixture.nodes["inventory-drawer-type"].value = "L";
  fixture.nodes.addPartInventoryForm.dispatchEvent(new Event("reset"));
  assert.equal(fixture.nodes["inventory-drawer-type"].value, "S");
  assert.equal(fixture.nodes["inventory-recommendation"].hidden, true);
});

test("save continuation carries the created part and snapshot target without placing it", async () => {
  const fixture = setup();
  fixture.select("altium", "10");
  await settle();
  const recommendation = fixture.window.InventoryRecommendation.snapshot();
  fixture.document.dispatchEvent(new DetailEvent("inventory:added", {part: {
    id: 99, library_source: "altium", external_part_id: "10", quantity: 2, name: "100nF",
  }, recommendation}));
  const url = new URL(fixture.nodes["inventory-placement-continue"].href, "http://localhost");
  assert.equal(url.pathname, "/warehouse");
  assert.equal(url.searchParams.get("part_id"), "99");
  assert.equal(url.searchParams.get("cabinet_id"), "BOX-000");
  assert.equal(url.searchParams.get("drawer_code"), "S-01");
  assert.equal(fixture.nodes["inventory-placement-notice"].hidden, false);
  assert.equal(fixture.calls.length, 1);
});

test("failed preview still permits continuation with only the real inventory ID", async () => {
  const fixture = setup({failure: true});
  fixture.select("altium", "10");
  await settle();
  const recommendation = fixture.window.InventoryRecommendation.snapshot();
  assert.equal(recommendation.recommended, null);
  fixture.document.dispatchEvent(new DetailEvent("inventory:added", {part: {
    id: 99, library_source: "altium", external_part_id: "10", quantity: 2,
  }, recommendation}));
  const url = new URL(fixture.nodes["inventory-placement-continue"].href, "http://localhost");
  assert.equal(url.searchParams.get("part_id"), "99");
  assert.equal(url.searchParams.get("drawer_code"), null);
});
