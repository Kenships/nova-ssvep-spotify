const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Execute the real hook/store with controlled React lifecycle and transport.
// No browser, live backend, or additional test dependencies are required.
function harness() {
  const effects = [];
  const timers = [];
  const sockets = [];
  const commands = [];
  const react = { useEffect: (fn) => effects.push(fn), useRef: (value) => ({ current: value }) };
  const load = (relative, imports) => {
    const filename = path.join(__dirname, "..", relative);
    const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const exports = {};
    vm.runInNewContext(code, {
      exports, require: (name) => imports[name] ?? require(name),
      window: { location: { protocol: "http:", host: "localhost:5173" } },
      localStorage: { getItem: () => null },
      WebSocket: Socket, setTimeout: (fn) => { timers.push(fn); return timers.length; },
      clearTimeout: () => {},
    }, { filename });
    return exports;
  };
  class Socket {
    static OPEN = 1;
    readyState = 0;
    sent = [];
    constructor() { sockets.push(this); }
    send(payload) { this.sent.push(JSON.parse(payload)); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; this.onopen(); }
    message(message) { this.onmessage({ data: JSON.stringify(message) }); }
  }
  const { usePlayerStore: store } = load("src/state/playerStore.ts", {});
  const select = (selector) => selector(store.getState());
  select.getState = store.getState;
  const { useCommandSocket } = load("src/ws/useCommandSocket.ts", {
    react, "../state/playerStore": { usePlayerStore: select },
  });
  useCommandSocket((command) => commands.push(command));
  return { store, sockets, commands, timers, mount: () => effects[0]() };
}

const transportState = { type: "state", layer: "transport", currentMoodId: "calm", calibrationActive: false };

test("reload restores backend layer and mood without firing a command", () => {
  const h = harness();
  h.mount();
  h.sockets[0].open();
  assert.equal(h.store.getState().serverStateReady, false);
  h.sockets[0].message(transportState);
  assert.equal(h.store.getState().layer, "transport");
  assert.equal(h.store.getState().currentMoodId, "calm");
  assert.equal(h.store.getState().serverStateReady, true);
  assert.equal(h.commands.length, 0);
});

test("calibration state survives reconnect and waits for a new snapshot", () => {
  const h = harness();
  h.mount();
  h.sockets[0].open();
  h.sockets[0].message({ ...transportState, calibrationActive: true });
  h.sockets[0].onclose();
  assert.equal(h.store.getState().serverStateReady, false);
  h.timers[0]();
  h.sockets[1].open();
  assert.equal(h.store.getState().serverStateReady, false);
  h.sockets[1].message({ ...transportState, calibrationActive: true });
  assert.equal(h.store.getState().calibrationActive, true);
  assert.equal(h.store.getState().serverStateReady, true);
});

test("StrictMode cleanup ignores late events from the discarded socket", () => {
  const h = harness();
  const cleanup = h.mount();
  cleanup();
  h.mount();
  h.sockets[1].open();
  h.sockets[1].message(transportState);
  h.sockets[0].onclose();
  h.sockets[0].message({ ...transportState, layer: "mood" });
  assert.equal(h.store.getState().wsStatus, "connected");
  assert.equal(h.store.getState().serverStateReady, true);
  assert.equal(h.store.getState().layer, "transport");
  assert.equal(h.timers.length, 0);
});

test("telemetry cannot overwrite the authoritative player layer", () => {
  const h = harness();
  h.mount();
  h.sockets[0].open();
  h.sockets[0].message(transportState);
  h.sockets[0].message({ type: "debug", layer: "mood", detectedLabel: "calm", confidence: 0.5, scores: {} });
  assert.equal(h.store.getState().layer, "transport");
  assert.equal(h.store.getState().detectionConfidence, 0.5);
});
