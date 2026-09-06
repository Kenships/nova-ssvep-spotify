import { useEffect, useRef } from "react";
import type { FreqTile } from "./frequencies";
import { SINE_MODULATION_DEPTH, type FlickerMode } from "./flickerModes";

interface FlickerCanvasProps {
  tiles: FreqTile[];
  highlightedTileId: string | null;
  mode: FlickerMode;
  onRefreshRateMeasured?: (hz: number) => void;
  /** Tiles must always be clickable, regardless of flicker mode -- for
   * testing without hardware, low-signal fallback during a demo, and as an
   * accessibility path for anyone who hasn't lost all voluntary movement.
   * Resolve true/false so the click gets an immediate, visible outcome --
   * a click that silently no-ops (e.g. rejected by the backend) must not
   * look identical to one that worked. */
  onTileActivate?: (tileId: string) => Promise<boolean>;
}

const REFRESH_MEASURE_FRAMES = 60;
const BACKGROUND = "#111318";
const PULSE_DURATION_MS = 550;
const CORNER_RADIUS_CSS_PX = 16;
type PulseStatus = "pending" | "ok" | "failed";
interface ClickPulse {
  start: number;
  status: PulseStatus;
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  return [
    parseInt(clean.substring(0, 2), 16),
    parseInt(clean.substring(2, 4), 16),
    parseInt(clean.substring(4, 6), 16),
  ];
}

interface PixelRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Where each tile lands, in pixel space, for the given canvas size. Shared
 * by the draw loop and the click hit-test so layout can never drift between
 * "what's drawn" and "what's clickable".
 *
 * If every tile specifies an explicit `rect` (fractions of the canvas --
 * see frequencies.ts), that layout is used as-is. Otherwise falls back to
 * an automatic square-ish grid (used by the mood tiles, which don't need a
 * specific arrangement).
 */
function computeTileRects(tiles: FreqTile[], width: number, height: number): PixelRect[] {
  if (tiles.length > 0 && tiles.every((t) => t.rect)) {
    const padding = Math.min(width, height) * 0.015;
    return tiles.map((t) => {
      const r = t.rect!;
      return {
        x: r.x * width + padding,
        y: r.y * height + padding,
        w: r.w * width - padding * 2,
        h: r.h * height - padding * 2,
      };
    });
  }

  const cols = Math.ceil(Math.sqrt(tiles.length));
  const rows = Math.ceil(tiles.length / cols);
  const cellW = width / cols;
  const cellH = height / rows;
  const padding = Math.min(cellW, cellH) * 0.08;
  return tiles.map((_, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    return {
      x: col * cellW + padding,
      y: row * cellH + padding,
      w: cellW - padding * 2,
      h: cellH - padding * 2,
    };
  });
}

/**
 * Frame-accurate SSVEP flicker rendering.
 *
 * Deliberately bypasses React's render cycle: a single requestAnimationFrame
 * loop owns all drawing, and each tile's stimulus state is computed directly
 * from elapsed frame time rather than from React state. React re-renders
 * cannot be trusted to land on a specific vsync -- setState -> DOM -> paint
 * has no frame-timing guarantee, and any drift here directly degrades SSVEP
 * detectability.
 *
 * Actual display refresh rate is measured from the first ~60 rAF callback
 * intervals rather than assumed to be 60Hz, since demo-venue displays vary.
 *
 * Supports multiple stimulus rendering styles (see flickerModes.ts) since a
 * hard 100%-depth color<->black square wave is more visually jarring than
 * the literature suggests is necessary for good detection accuracy.
 */
export function FlickerCanvas({
  tiles,
  highlightedTileId,
  mode,
  onRefreshRateMeasured,
  onTileActivate,
}: FlickerCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);
  // Lives outside the effect below so a click's feedback survives the
  // effect re-running (which happens on every highlightedTileId change --
  // i.e. often, since automatic detections update it independently of any
  // click). A plain `const pulses = new Map()` declared inside the effect
  // would get silently reset mid-animation.
  const pulsesRef = useRef<Map<string, ClickPulse>>(new Map());

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    };
    resize();
    window.addEventListener("resize", resize);

    let frameCount = 0;
    let startTime: number | null = null;
    let lastFrameTimestamps: number[] = [];
    let measurementReported = false;

    const drawSine = (ctx: CanvasRenderingContext2D, tile: FreqTile, x: number, y: number, w: number, h: number, t: number) => {
      const s = (Math.sin(2 * Math.PI * tile.freqHz * t) + 1) / 2; // 0..1
      const brightness = 1 - SINE_MODULATION_DEPTH + SINE_MODULATION_DEPTH * s; // e.g. [0.45, 1]
      const [r, g, b] = hexToRgb(tile.color);
      ctx.fillStyle = `rgb(${r * brightness}, ${g * brightness}, ${b * brightness})`;
      ctx.fillRect(x, y, w, h);
    };

    const drawRings = (ctx: CanvasRenderingContext2D, tile: FreqTile, x: number, y: number, w: number, h: number, t: number) => {
      ctx.fillStyle = BACKGROUND;
      ctx.fillRect(x, y, w, h);
      const cx = x + w / 2;
      const cy = y + h / 2;
      const maxR = (Math.min(w, h) / 2) * 0.9;
      const nRings = 5;
      const pulse = 1 + 0.18 * Math.sin(2 * Math.PI * tile.freqHz * t); // breathing scale
      for (let i = nRings; i >= 1; i--) {
        const r = Math.max((maxR * i) / nRings, 0) * pulse;
        ctx.beginPath();
        ctx.fillStyle = i % 2 === 0 ? BACKGROUND : tile.color;
        ctx.arc(cx, cy, r, 0, 2 * Math.PI);
        ctx.fill();
      }
    };

    const drawCheckerboard = (ctx: CanvasRenderingContext2D, tile: FreqTile, x: number, y: number, w: number, h: number, t: number) => {
      // Pattern-reversal: which cells are "on" flips at the target
      // frequency, but roughly half the tile is always lit -- mean
      // luminance stays constant, unlike color<->black flicker.
      //
      // Cols/rows are picked so cellW*cols and cellH*rows land exactly on w
      // and h -- a fixed pixel cell size stepped from the tile's corner
      // leaves a leftover partial strip on the bottom/right edge whenever
      // w/h isn't an exact multiple of it, which reads as off-center
      // (worse once tiles stopped being uniform grid cells -- see the
      // media-player transport layout).
      const phase = Math.sin(2 * Math.PI * tile.freqHz * t) >= 0;
      const targetCellSize = Math.max(Math.min(w, h) / 6, 4);
      const cols = Math.max(1, Math.round(w / targetCellSize));
      const rows = Math.max(1, Math.round(h / targetCellSize));
      const cellW = w / cols;
      const cellH = h / rows;
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const evenCell = (row + col) % 2 === 0;
          const lit = phase ? evenCell : !evenCell;
          ctx.fillStyle = lit ? tile.color : BACKGROUND;
          ctx.fillRect(x + col * cellW, y + row * cellH, cellW, cellH);
        }
      }
    };

    const drawGabor = (ctx: CanvasRenderingContext2D, tile: FreqTile, x: number, y: number, w: number, h: number, t: number) => {
      // Approximation of a reversing grating, not a literature-precise
      // Gaussian-windowed Gabor patch -- flagged as experimental in
      // flickerModes.ts since comfort claims for this one weren't
      // independently verified.
      const stripeCount = 10;
      const phaseShift = Math.sin(2 * Math.PI * tile.freqHz * t) >= 0 ? 0 : Math.PI;
      const [r, g, b] = hexToRgb(tile.color);
      const stripeWidth = 3;
      for (let i = 0; i < w; i += stripeWidth) {
        const spatialPhase = (i / w) * 2 * Math.PI * stripeCount + phaseShift;
        const intensity = (Math.sin(spatialPhase) + 1) / 2;
        ctx.fillStyle = `rgb(${r * intensity}, ${g * intensity}, ${b * intensity})`;
        ctx.fillRect(x + i, y, stripeWidth, h);
      }
    };

    const drawOff = (ctx: CanvasRenderingContext2D, tile: FreqTile, x: number, y: number, w: number, h: number) => {
      ctx.fillStyle = tile.color;
      ctx.fillRect(x, y, w, h);
    };

    const draw = (timestamp: number) => {
      if (startTime === null) startTime = timestamp;
      frameCount += 1;

      // Measure actual refresh rate from real frame intervals.
      lastFrameTimestamps.push(timestamp);
      if (lastFrameTimestamps.length > REFRESH_MEASURE_FRAMES) {
        lastFrameTimestamps.shift();
      }
      if (lastFrameTimestamps.length === REFRESH_MEASURE_FRAMES && !measurementReported) {
        const span = lastFrameTimestamps[lastFrameTimestamps.length - 1] - lastFrameTimestamps[0];
        const measuredRefreshHz = ((REFRESH_MEASURE_FRAMES - 1) / span) * 1000;
        measurementReported = true;
        onRefreshRateMeasured?.(measuredRefreshHz);
      }

      const elapsedSec = (timestamp - startTime) / 1000;
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      const tileRects = computeTileRects(tiles, width, height);

      tiles.forEach((tile, i) => {
        const { x, y, w, h } = tileRects[i];
        // Fixed CSS-pixel radius (scaled to device pixels), not proportional
        // to tile size -- real UI corner radii stay constant regardless of
        // how big the element is. Capped at half the smaller side so a
        // short strip like the "Back to Playlists" footer doesn't turn
        // into an unintended full pill/stadium shape.
        const radius = Math.min(CORNER_RADIUS_CSS_PX * dpr, Math.min(w, h) / 2);

        // Rounded corners for a modern look: clip to a rounded rect before
        // any stimulus mode draws, so sine/rings/checkerboard/gabor all
        // respect the shape without each needing its own rounding logic.
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, radius);
        ctx.clip();
        switch (mode) {
          case "sine":
            drawSine(ctx, tile, x, y, w, h, elapsedSec);
            break;
          case "rings":
            drawRings(ctx, tile, x, y, w, h, elapsedSec);
            break;
          case "checkerboard":
            drawCheckerboard(ctx, tile, x, y, w, h, elapsedSec);
            break;
          case "gabor":
            drawGabor(ctx, tile, x, y, w, h, elapsedSec);
            break;
          case "off":
            drawOff(ctx, tile, x, y, w, h);
            break;
        }
        ctx.restore();

        if (tile.id === highlightedTileId) {
          ctx.beginPath();
          ctx.roundRect(x, y, w, h, radius);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = Math.max(4, w * 0.02);
          ctx.stroke();
        }

        // Legible label regardless of the mode's instantaneous pixel colors
        // underneath: a dark pill behind light text.
        const fontSize = Math.round(h * 0.12);
        ctx.font = `${fontSize}px system-ui, sans-serif`;
        const textWidth = ctx.measureText(tile.label).width;
        const padX = fontSize * 0.6;
        const padY = fontSize * 0.35;
        ctx.fillStyle = "rgba(10, 10, 12, 0.55)";
        ctx.fillRect(
          x + w / 2 - textWidth / 2 - padX,
          y + h / 2 - fontSize / 2 - padY,
          textWidth + padX * 2,
          fontSize + padY * 2,
        );
        ctx.fillStyle = "#f2f2f2";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(tile.label, x + w / 2, y + h / 2);

        // Immediate click feedback: an expanding, fading ring drawn on top
        // of everything else, independent of any backend round-trip --
        // white while the request is in flight, green/red once it
        // resolves. This is what makes a click feel like it *did
        // something* the instant it happens, rather than waiting on a
        // network response (or silently doing nothing if one is rejected).
        const pulse = pulsesRef.current.get(tile.id);
        if (pulse) {
          const age = timestamp - pulse.start;
          if (age > PULSE_DURATION_MS) {
            pulsesRef.current.delete(tile.id);
          } else {
            const progress = age / PULSE_DURATION_MS;
            const color = pulse.status === "failed" ? "255, 82, 82" : pulse.status === "ok" ? "76, 217, 100" : "255, 255, 255";
            const alpha = pulse.status === "pending" ? 0.7 : 0.7 * (1 - progress);
            const inset = Math.min(w, h) * 0.04 * progress;
            ctx.strokeStyle = `rgba(${color}, ${alpha})`;
            ctx.lineWidth = Math.max(6, w * 0.035) * (1 - progress * 0.5);
            ctx.beginPath();
            ctx.roundRect(
              x + inset,
              y + inset,
              w - inset * 2,
              h - inset * 2,
              Math.max(radius - inset, 0),
            );
            ctx.stroke();
          }
        }
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    const handleClick = (event: MouseEvent) => {
      if (!onTileActivate) return;
      const rect = canvas.getBoundingClientRect();
      const clickX = event.clientX - rect.left;
      const clickY = event.clientY - rect.top;
      const tileRects = computeTileRects(tiles, rect.width, rect.height);
      const index = tileRects.findIndex(
        (r) => clickX >= r.x && clickX <= r.x + r.w && clickY >= r.y && clickY <= r.y + r.h,
      );
      const tile = tiles[index];
      if (!tile) return;

      pulsesRef.current.set(tile.id, { start: performance.now(), status: "pending" });
      onTileActivate(tile.id).then((ok) => {
        const pulse = pulsesRef.current.get(tile.id);
        if (pulse && pulse.status === "pending") {
          pulse.status = ok ? "ok" : "failed";
          pulse.start = performance.now(); // restart the fade from resolution, not from click time
        }
      });
    };
    canvas.addEventListener("click", handleClick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("click", handleClick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tiles, highlightedTileId, mode, onTileActivate]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "100%", display: "block", cursor: onTileActivate ? "pointer" : "default" }}
    />
  );
}
