import { useEffect, useRef } from "react";
import { ConnectedDevice } from "./ConnectedDevice";
import { useCanvasResizeObserver } from "../canvas/useCanvasResizeObserver";
import { labelForTileId } from "../ssvep/frequencies";
import { usePlayerStore } from "../state/playerStore";

const CHANNEL_COLORS = ["#4FC3F7", "#FFD54F", "#FF7043", "#7986CB", "#81C784", "#BA68C8"];

/** Redraws the last ~1s of raw occipital channel data every time a new "raw"
 * WS message lands -- data itself only updates a few times a second, so a
 * one-shot draw per message is enough; no rAF loop needed here. Each
 * channel is independently autoscaled to its own min/max, like a typical
 * EEG viewer, so a low-amplitude channel doesn't look flat next to a noisy one.
 *
 * Also redraws on any layout resize of the canvas itself, via the same
 * ResizeObserver-based hook FlickerCanvas uses: this canvas sits inside the
 * panel's own width-animating container, so opening/closing the panel
 * resizes it without ever firing a window resize event. Without that, the
 * canvas's drawing buffer would keep whatever size it had at the last data
 * update instead of the panel's current width, stretching the trace.
 */
function RawChannelGraph() {
  const rawChannelData = usePlayerStore((s) => s.rawChannelData);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dataRef = useRef(rawChannelData);
  dataRef.current = rawChannelData;

  const draw = () => {
    const canvas = canvasRef.current;
    const data = dataRef.current;
    if (!canvas || !data || data.samples.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // canvas.width/height are already kept in sync with layout by
    // useCanvasResizeObserver below -- just read them, don't resize here.
    const dpr = window.devicePixelRatio || 1;

    const { samples, channelLabels } = data;
    const nChannels = channelLabels.length;
    const width = canvas.width;
    const height = canvas.height;
    const rowH = height / Math.max(nChannels, 1);

    ctx.clearRect(0, 0, width, height);

    for (let ch = 0; ch < nChannels; ch++) {
      const values = samples.map((s) => s[ch]);
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const baseY = ch * rowH;
      const color = CHANNEL_COLORS[ch % CHANNEL_COLORS.length];

      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(1, dpr);
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * width;
        const norm = (v - min) / span; // 0..1, this channel's own scale
        const y = baseY + rowH - norm * rowH * 0.8 - rowH * 0.1;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.fillStyle = color;
      ctx.font = `${11 * dpr}px system-ui, sans-serif`;
      ctx.fillText(channelLabels[ch], 4 * dpr, baseY + 12 * dpr);
    }
  };

  useEffect(() => {
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawChannelData]);

  useCanvasResizeObserver(canvasRef, draw);

  if (!rawChannelData || rawChannelData.samples.length === 0) {
    return <div className="debug-panel__empty">Waiting for channel data…</div>;
  }

  return <canvas ref={canvasRef} className="debug-panel__graph" />;
}

function ConfidenceBars() {
  const scores = usePlayerStore((s) => s.detectionScores);
  const detectedLabel = usePlayerStore((s) => s.detectedLabel);
  const entries = Object.entries(scores).sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) {
    return <div className="debug-panel__empty">No detections yet</div>;
  }

  return (
    <div className="debug-panel__bars">
      {entries.map(([id, confidence]) => (
        <div key={id} className="debug-panel__bar-row">
          <span className="debug-panel__bar-label">{labelForTileId(id)}</span>
          <div className="debug-panel__bar-track">
            <div
              className={
                id === detectedLabel
                  ? "debug-panel__bar-fill debug-panel__bar-fill--active"
                  : "debug-panel__bar-fill"
              }
              style={{ width: `${Math.min(100, Math.max(0, confidence * 100))}%` }}
            />
          </div>
          <span className="debug-panel__bar-value">{confidence.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

function useDebugPanelToggle() {
  const open = usePlayerStore((s) => s.debugPanelOpen);
  const setOpen = usePlayerStore((s) => s.setDebugPanelOpen);
  const sendRawSubscription = usePlayerStore((s) => s.sendRawSubscription);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    sendRawSubscription?.(next);
  };

  // sendRawSubscription starts null and is populated once useCommandSocket's
  // effect runs; if the panel is already open by the time that happens (or
  // after a reconnect hands us a new function reference), make sure the
  // subscription actually goes out instead of silently staying unsent.
  useEffect(() => {
    if (open) sendRawSubscription?.(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendRawSubscription]);

  return { open, toggle };
}

/** Header button that opens/closes the debug panel. Rendered separately from
 * DebugPanelContent so it can live in the header while the panel itself
 * docks as a layout sibling of the main app column (see app-shell in
 * App.tsx) -- that's what lets the panel push the UI over instead of
 * floating on top of it. */
export function DebugPanelToggle() {
  const { open, toggle } = useDebugPanelToggle();
  return (
    <button className="debug-panel__trigger" onClick={toggle} aria-label="Debug panel" aria-expanded={open}>
      📊
    </button>
  );
}

/** Docked side panel: raw occipital channel traces + per-frequency
 * confidence, for tuning signal quality / dwell / threshold live rather
 * than guessing from the single winning confidence number in the footer.
 * Raw samples are only streamed from the backend while this is open (see
 * useCommandSocket's raw_subscribe/raw_unsubscribe) -- opening/closing it
 * has no effect on the confidence bars, which ride the always-on debug tick.
 *
 * Always mounted (width animates 0 <-> full via CSS, gated by
 * debug-panel-dock--open) rather than conditionally rendered, so the rest of
 * the layout smoothly shifts over instead of jump-cutting to a new width.
 */
export function DebugPanelContent() {
  const { open, toggle } = useDebugPanelToggle();

  return (
    <div className={open ? "debug-panel-dock debug-panel-dock--open" : "debug-panel-dock"}>
      <aside className="debug-panel">
        <div className="debug-panel__header">
          <span>Debug</span>
          <button className="debug-panel__close" onClick={toggle} aria-label="Close debug panel">
            ✕
          </button>
        </div>
        <div className="debug-panel__section">
          <div className="debug-panel__section-title">Connected device</div>
          {open && <ConnectedDevice />}
        </div>
        <div className="debug-panel__section">
          <div className="debug-panel__section-title">Confidence by frequency</div>
          <ConfidenceBars />
        </div>
        <div className="debug-panel__section">
          <div className="debug-panel__section-title">Raw channel data</div>
          <RawChannelGraph />
        </div>
      </aside>
    </div>
  );
}
