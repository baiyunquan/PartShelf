const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("static/js/warehouse_placement.js", "utf8");
const translations = JSON.parse(fs.readFileSync("app/i18n/locales/en.json", "utf8")).warehouse;
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settle() { await tick(); await tick(); }

class Element extends EventTarget {
  constructor() { super(); this.value = ""; this.files = []; this.disabled = false; this.hidden = false; this.children = []; this.dataset = {}; this.classList = {toggle() {}}; }
  replaceChildren(...children) { this.children = children; this.value = ""; }
  add(child) { this.children.push(child); }
  removeAttribute() {}
  reportValidity() { return true; }
  closest() { return this.dataset.removePartId ? this : null; }
}
class DetailEvent extends Event {
  constructor(type, options) { super(type); this.detail = options.detail; }
}

function setup({placed = false, conflict = false, delayedSuggestions = false, empty = false, noStock = false} = {}) {
  const ids = ["page-translations", "warehouse-placement-form", "warehouse-part-select", "warehouse-drawer-type",
    "warehouse-placement-target", "warehouse-photo", "warehouse-photo-preview", "warehouse-placement-message",
    "warehouse-placement-confirm", "warehouse-part-search", "warehouse-part-search-button", "warehouse-drawer-parts"];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements["page-translations"].textContent = JSON.stringify(translations);
  const document = new EventTarget();
  document.getElementById = id => elements[id];
  elements["warehouse-placement-form"].elements = ids.filter(id => !id.includes("translations")).map(id => elements[id]);
  const calls = [], events = [], pending = [];
  document.addEventListener("warehouse:show-drawer", event => events.push(event.detail));
  document.addEventListener("warehouse:refresh", () => events.push("refresh"));
  const part = {id: 7, name: "100nF", package: "0603", quantity: noStock ? 0 : 3, warehouse_status: placed ? "in_warehouse" : "not_in_warehouse",
    warehouse_box_id: "BOX-001", warehouse_drawer_code: "S-05"};
  const response = (body, status = 200) => ({ok: status === 200, status, json: async () => body});
  const suggestion = url => {
    const drawerType = url.includes("drawer_type=L") ? "L" : "S";
    return response({group: {label: "0.0000001 F"}, reason: "empty", candidates: [1, 2].map(index => ({
      cabinet_id: "BOX-000", drawer_code: `${drawerType}-0${index}`, state: "empty",
    }))});
  };
  const fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (url.includes("/suggestion")) {
      if (delayedSuggestions) return new Promise(resolve => pending.push(() => resolve(suggestion(url))));
      return suggestion(url);
    }
    if (url.includes("/placement")) return response({}, options.method === "POST" && conflict ? 409 : 200);
    if (url.includes("get_part_by_id")) return response(part);
    return response(placed || empty ? [] : [part]);
  };
  vm.runInNewContext(source, {
    document, fetch, window: {location: {search: empty || noStock ? "" : "?part_id=7"}, confirm: () => true},
    Option: function(label, value) { this.text = label; this.value = value; },
    Event, CustomEvent: DetailEvent, URLSearchParams, FormData,
    URL: {createObjectURL: () => "blob:photo", revokeObjectURL() {}},
  });
  return {elements, calls, events, pending};
}

async function selectType(fixture, type = "S") {
  const control = fixture.elements["warehouse-drawer-type"];
  control.value = type;
  control.dispatchEvent(new Event("change"));
  await settle();
}
async function uploadPhoto(fixture) {
  const photo = fixture.elements["warehouse-photo"];
  photo.files = [new Blob(["photo"], {type: "image/png"})];
  photo.dispatchEvent(new Event("change"));
  await settle();
}

test("requires a drawer type and photo, then submits the chosen alternative", async () => {
  const fixture = setup();
  await settle();
  assert.equal(fixture.elements["warehouse-part-select"].value, "7");
  assert.equal(fixture.elements["warehouse-placement-confirm"].disabled, true);
  assert.equal(fixture.calls.filter(call => call.url.includes("suggestion")).length, 0);
  await selectType(fixture);
  assert.equal(fixture.elements["warehouse-placement-confirm"].disabled, true);
  await uploadPhoto(fixture);
  assert.equal(fixture.elements["warehouse-placement-confirm"].disabled, false);
  fixture.elements["warehouse-placement-target"].value = "1";
  fixture.elements["warehouse-placement-form"].dispatchEvent(new Event("submit", {cancelable: true}));
  await settle();
  const post = fixture.calls.find(call => call.options.method === "POST");
  assert.equal(post.url, "/api/warehouse/parts/7/placement");
  assert.equal(post.options.body.get("drawer_code"), "S-02");
  assert.equal(post.options.body.get("photo").type, "image/png");
  assert.ok(fixture.events.includes("refresh"));
  assert.equal(fixture.elements["warehouse-placement-message"].textContent, translations.placement_saved);
});

test("a stale suggestion cannot replace the newly selected drawer type", async () => {
  const fixture = setup({delayedSuggestions: true});
  await settle();
  await selectType(fixture, "S");
  await selectType(fixture, "L");
  fixture.pending[1]();
  await settle();
  fixture.pending[0]();
  await settle();
  assert.ok(fixture.elements["warehouse-placement-target"].children.every(option => option.text.includes("L-")));
});

test("conflict refreshes suggestions and reports the changed state", async () => {
  const fixture = setup({conflict: true});
  await settle();
  await selectType(fixture);
  await uploadPhoto(fixture);
  fixture.elements["warehouse-placement-form"].dispatchEvent(new Event("submit", {cancelable: true}));
  await settle();
  assert.equal(fixture.calls.filter(call => call.url.includes("suggestion")).length, 2);
  assert.equal(fixture.elements["warehouse-placement-message"].textContent, translations.placement_conflict);
  assert.equal(fixture.elements["warehouse-placement-confirm"].disabled, false);
});

test("existing placement opens the drawer immediately from the details link", async () => {
  const fixture = setup({placed: true});
  await settle();
  assert.equal(fixture.events[0].cabinet_id, "BOX-001");
  assert.equal(fixture.events[0].drawer_code, "S-05");
});

for (const configuration of [{empty: true}, {noStock: true}]) {
  test(`empty selection explains how to add stock (${JSON.stringify(configuration)})`, async () => {
    const fixture = setup(configuration);
    await settle();
    assert.equal(fixture.elements["warehouse-part-select"].children.length, 1);
    assert.equal(fixture.elements["warehouse-placement-message"].textContent, translations.placement_no_parts);
    assert.equal(fixture.elements["warehouse-placement-confirm"].disabled, true);
  });
}
