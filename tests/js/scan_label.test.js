const test = require("node:test");
const assert = require("node:assert/strict");
const label = require("../../static/js/scan_label.js");

test("real JLC payload supplies a safe model, code and package quantity", () => {
  const parsed = label.parse("{on:SO26042924401,pc:C965815,pm:XL-2012UGC,qty:100,mc:,cc:1,pdi:211463771,hp:11}");
  assert.equal(parsed.pc, "C965815");
  assert.equal(parsed.qty, 100);
  assert.equal(parsed.pm, "XL-2012UGC");
  assert.throws(() => label.parse("{pc:C965815,pm:XL,qty:0}"));
  assert.throws(() => label.parse("{pc:C965815,pc:C6119867,pm:XL,qty:1}"));
});

test("the saved project remains selected and deleted/system projects fall back to inventory", () => {
  const projects = [{id: 1, is_system: false}, {id: 2, is_system: false}, {id: 3, is_system: true}];
  assert.equal(label.projectChoice(projects, "2"), "2");
  assert.equal(label.projectChoice(projects, "3"), "");
  assert.equal(label.projectChoice(projects, "42"), "");
});

test("project identity rejects a reused ID but survives a rename", () => {
  const options = [{id: 2, name: "Renamed project", identity_token: "original"}];
  assert.equal(label.projectChoice(options, "2", "original"), "2");
  assert.equal(label.projectChoice(options, "2", "replaced"), "");
});

test("an explicit new bag action releases camera repeat suppression", () => {
  const seen = new Set(["same packaging QR"]);
  label.repeatCameraScan(seen);
  assert.equal(seen.has("same packaging QR"), false);
});

test("a JLC identity with missing quantity remains on the QR review path", () => {
  const result = label.decodeChoice([{text: "{pc:C541722,qty:0}"}]);
  assert.equal(result.kind, "jlc");
  assert.equal(result.label.pc, "C541722");
  assert.equal(result.label.qty, null);
});

test("two JLC labels are never silently reduced to the first QR", () => {
  const result = label.decodeChoice([
    {text: "{pc:C541722,pm:AO3400C,qty:5}"},
    {text: "{pc:C473048,pm:0201WMF1002TEE,qty:100}"},
  ]);
  assert.equal(result.kind, "multiple");
  assert.equal(result.qr_texts.length, 2);
});

test("candidate confirmation always carries its catalog namespace", () => {
  const result = label.confirmationIdentity("31355", {library_source: "altium", external_part_id: "31355"});
  assert.deepEqual(result, {library_source: "altium", external_part_id: "31355"});
  assert.deepEqual(label.confirmationIdentity("C541722", null), {lcsc_code: "C541722"});
  assert.deepEqual(label.confirmationIdentity("C965815", {library_source: "altium", external_part_id: "31355"}), {lcsc_code: "C965815"});
});
