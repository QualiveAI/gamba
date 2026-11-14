"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadPreview() {
  const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const context = {
    document: { querySelector: () => ({ addEventListener() {}, value: "", textContent: "", innerHTML: "", classList: { toggle() {} } }) },
    globalThis: {},
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.WindropPredictorPreview;
}

test("simulation is deterministic for the same seed", () => {
  const preview = loadPreview();
  const a = preview.simulate({ game: "crash", mode: "biased", rounds: 500, seed: "same" });
  const b = preview.simulate({ game: "crash", mode: "biased", rounds: 500, seed: "same" });
  assert.deepEqual(a, b);
});

test("anti-pattern preview visibly changes quality by stake bucket", () => {
  const preview = loadPreview();
  const rows = preview.simulate({ game: "mines", mode: "biased", rounds: 1000, seed: "quality" });
  assert.ok(rows[0].accuracy > rows[2].accuracy);
  assert.ok(rows[0].losses < rows[2].losses);
});

test("fair baseline does not use stake-dependent accuracy", () => {
  const preview = loadPreview();
  const rows = preview.simulate({ game: "cups", mode: "fair", rounds: 1000, seed: "fair" });
  assert.ok(Math.abs(rows[0].accuracy - rows[2].accuracy) < 0.06);
});

test("preview source has no network, payment or live identity paths", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  const app = fs.readFileSync(path.join(root, "app.js"), "utf8");
  assert.doesNotMatch(app, /fetch\s*\(|XMLHttpRequest|WebSocket|session_id|user_id|https?:\/\//i);
  assert.match(html, /ANTI-PATTERN/);
});
