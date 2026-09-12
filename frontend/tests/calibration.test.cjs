const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(relative, globals) {
  const filename = path.join(__dirname, "..", relative);
  const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require, AbortController, ...globals }, { filename });
  return exports;
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const good = { label: "calm", ready: true, snr: 6, ok: true };
const response = (value) => ({ ok: true, json: async () => value });

function cueHarness(fetcher = async () => response(good)) {
  let now = 0, nextId = 0;
  const timers = new Map();
  const schedule = (fn, ms, repeat = 0) => {
    const id = ++nextId;
    timers.set(id, { fn, due: now + ms, repeat });
    return id;
  };
  const calls = [], updates = [], results = [];
  const { runCalibrationCue } = load("src/calibration/runCalibrationCue.ts", {
    performance: { now: () => now },
    setTimeout: (fn, ms) => schedule(fn, ms), clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, ms) => schedule(fn, ms, ms), clearInterval: (id) => timers.delete(id),
    fetch: (url, options) => { calls.push({ at: now, url, options }); return fetcher(now, options); },
  });
  const advance = async (ms) => {
    const target = now + ms;
    while (true) {
      const next = [...timers.entries()].filter(([, t]) => t.due <= target).sort((a, b) => a[1].due - b[1].due)[0];
      if (!next) break;
      const [id, timer] = next;
      now = timer.due;
      timers.delete(id);
      if (timer.repeat) timers.set(id, { ...timer, due: now + timer.repeat });
      timer.fn();
      await flush();
    }
    now = target;
    await flush();
  };
  return { calls, updates, results, advance, timers,
    start: (windowSec = 2) => runCalibrationCue("calm", windowSec, (u) => updates.push(u), (r) => results.push(r)),
  };
}

test("each cue waits for the configured analysis window and returns a fresh reading", async () => {
  const h = cueHarness();
  h.start(3);
  await h.advance(2999);
  assert.equal(h.calls.length, 0);
  await h.advance(5001);
  assert.equal(h.calls[0].at, 3000);
  assert.equal(h.results.length, 1);
  assert.equal(h.results[0].snr, 6);
  assert.equal(h.timers.size, 0);
});

test("a failed request clears an earlier good reading before completing", async () => {
  const h = cueHarness(async (now) => {
    if (now >= 5000) throw new Error("offline");
    return response(good);
  });
  h.start();
  await h.advance(8000);
  assert.ok(h.updates.some((u) => u.reading?.ok));
  assert.equal(h.updates.at(-1).reading, null);
  assert.match(h.updates.at(-1).message, /connection/);
  assert.equal(h.results[0], null);
});

test("requests never overlap and a hung response cannot preserve stale success", async () => {
  const h = cueHarness(async (now) => now < 3000 ? response(good) : new Promise(() => {}));
  h.start();
  await h.advance(8000);
  assert.equal(h.calls.length, 3);
  assert.equal(h.calls.at(-1).options.signal.aborted, true);
  assert.equal(h.results[0], null);
});

test("leaving a cue aborts its request and ignores late responses", async () => {
  let resolve;
  const h = cueHarness(() => new Promise((done) => { resolve = done; }));
  const stop = h.start();
  await h.advance(2000);
  stop();
  const updateCount = h.updates.length;
  assert.equal(h.calls[0].options.signal.aborted, true);
  resolve(response(good));
  await flush();
  await h.advance(10000);
  assert.equal(h.updates.length, updateCount);
  assert.equal(h.results.length, 0);
});

test("wrong-target and nonfinite SNR responses cannot become results", async () => {
  for (const data of [{ ...good, label: "sad" }, { ...good, snr: NaN }, { ...good, ready: false }]) {
    const h = cueHarness(async () => response(data));
    h.start();
    await h.advance(8000);
    assert.equal(h.results[0], null);
  }
});

test("long analysis windows still allow four seconds to collect measurements", async () => {
  const h = cueHarness();
  h.start(10);
  await h.advance(10000);
  assert.equal(h.results.length, 0);
  assert.equal(h.calls[0].at, 10000);
  await h.advance(4000);
  assert.equal(h.results[0].snr, 6);
});

test("countdown and live-reading rerenders preserve the calibration tile array", async () => {
  let cursor = 0;
  const cells = [], pendingEffects = [], cueUpdates = [];
  const react = {
    useState: (initial) => {
      const index = cursor++;
      if (!(index in cells)) cells[index] = initial;
      return [cells[index], (value) => { cells[index] = typeof value === "function" ? value(cells[index]) : value; }];
    },
    useRef: (value) => { const index = cursor++; return cells[index] ??= { current: value }; },
    useMemo: (factory, deps) => {
      const index = cursor++;
      if (!cells[index] || deps.some((d, i) => d !== cells[index].deps[i])) cells[index] = { deps, value: factory() };
      return cells[index].value;
    },
    useEffect: (effect, deps) => {
      const index = cursor++;
      if (!cells[index] || deps.some((d, i) => d !== cells[index][i])) pendingEffects.push(effect);
      cells[index] = deps;
    },
  };
  const FlickerCanvas = () => null;
  const imports = {
    react,
    "../ssvep/FlickerCanvas": { FlickerCanvas },
    "../ssvep/frequencies": { MOOD_TILES: [{ id: "calm", label: "Calm", freqHz: 15 }] },
    "../state/playerStore": { usePlayerStore: (selector) => selector({ flickerMode: "sine" }) },
    "./runCalibrationCue": { runCalibrationCue: (_id, _window, update) => { cueUpdates.push(update); return () => {}; } },
  };
  const { CalibrationScreen } = load("src/calibration/CalibrationScreen.tsx", {
    require: (name) => imports[name] ?? require(name),
    fetch: async () => response({ window_sec: 2 }), setTimeout: () => 1, clearTimeout: () => {},
  });
  const render = () => {
    cursor = 0;
    const tree = CalibrationScreen({ onDone: () => {} });
    while (pendingEffects.length) pendingEffects.shift()();
    return tree;
  };
  const find = (node, predicate) => {
    if (!node || typeof node !== "object") return null;
    if (predicate(node)) return node;
    for (const child of [node.props?.children].flat(Infinity)) {
      const found = find(child, predicate);
      if (found) return found;
    }
    return null;
  };
  const intro = render();
  find(intro, (n) => n.type === "button" && n.props.children === "Start signal check").props.onClick();
  await flush();
  const first = find(render(), (n) => n.type === FlickerCanvas);
  cueUpdates[0]({ secondsLeft: 6, reading: good, message: null });
  const second = find(render(), (n) => n.type === FlickerCanvas);
  assert.strictEqual(first.props.tiles, second.props.tiles);
  cueUpdates[0]({ secondsLeft: 5, reading: { ...good, snr: 2.5, ok: false }, message: null });
  const atTwo = render();
  assert.ok(find(atTwo, (n) => n.props?.role === "status" && String(n.props.children).includes("Above SNR threshold")));
  find(atTwo, (n) => n.props?.id === "calibration-snr-cutoff").props.onChange({ target: { value: "3" } });
  const atThree = render();
  assert.ok(find(atThree, (n) => n.props?.role === "status" && String(n.props.children).includes("Below SNR threshold")));
  assert.strictEqual(find(atThree, (n) => n.type === FlickerCanvas).props.tiles, first.props.tiles);
  assert.equal(cueUpdates.length, 1, "changing the display cutoff must not restart acquisition");
});
