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
   * accessibility path for anyone who hasn't lost all voluntary movement. */
  onTileActivate?: (tileId: string) => void;
}

const REFRESH_MEASURE_FRAMES = 60;
const BACKGROUND = "#111318";

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  return [
    parseInt(clean.substring(0, 2), 16),
    parseInt(clean.substring(2, 4), 16),
    parseInt(clean.substring(4, 6), 16),
  ];
}

function getGridDims(n: number) {
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  return { cols, rows };
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
      const phase = Math.sin(2 * Math.PI * tile.freqHz * t) >= 0;
      const checkSize = Math.max(Math.min(w, h) / 6, 4);
      for (let cy = 0; cy < h; cy += checkSize) {
        for (let cx = 0; cx < w; cx += checkSize) {
          const evenCell = (Math.floor((x + cx) / checkSize) + Math.floor((y + cy) / checkSize)) % 2 === 0;
          const lit = phase ? evenCell : !evenCell;
          ctx.fillStyle = lit ? tile.color : BACKGROUND;
          ctx.fillRect(x + cx, y + cy, checkSize, checkSize);
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

      const { cols, rows } = getGridDims(tiles.length);
      const cellW = width / cols;
      const cellH = height / rows;
      const padding = Math.min(cellW, cellH) * 0.08;

      tiles.forEach((tile, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const x = col * cellW + padding;
        const y = row * cellH + padding;
        const w = cellW - padding * 2;
        const h = cellH - padding * 2;

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

        if (tile.id === highlightedTileId) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = Math.max(4, w * 0.02);
          ctx.strokeRect(x, y, w, h);
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
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    const handleClick = (event: MouseEvent) => {
      if (!onTileActivate) return;
      const rect = canvas.getBoundingClientRect();
      const clickX = event.clientX - rect.left;
      const clickY = event.clientY - rect.top;
      const { cols, rows } = getGridDims(tiles.length);
      const col = Math.floor(clickX / (rect.width / cols));
      const row = Math.floor(clickY / (rect.height / rows));
      const index = row * cols + col;
      const tile = tiles[index];
      if (tile) onTileActivate(tile.id);
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
