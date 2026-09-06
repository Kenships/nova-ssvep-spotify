import { useEffect, useRef } from "react";
import type { FreqTile } from "./frequencies";

interface FlickerCanvasProps {
  tiles: FreqTile[];
  highlightedTileId: string | null;
  onRefreshRateMeasured?: (hz: number) => void;
}

const REFRESH_MEASURE_FRAMES = 60;

/**
 * Frame-accurate SSVEP flicker rendering.
 *
 * Deliberately bypasses React's render cycle: a single requestAnimationFrame
 * loop owns all drawing, and each tile's on/off state is computed directly
 * from elapsed frame time via sign(sin(2*pi*f*t)) rather than from React
 * state. React re-renders cannot be trusted to land on a specific vsync --
 * setState -> DOM -> paint has no frame-timing guarantee, and any drift
 * here directly degrades SSVEP detectability.
 *
 * Actual display refresh rate is measured from the first ~60 rAF callback
 * intervals rather than assumed to be 60Hz, since demo-venue displays vary.
 */
export function FlickerCanvas({ tiles, highlightedTileId, onRefreshRateMeasured }: FlickerCanvasProps) {
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
    let measuredRefreshHz = 60;
    let measurementReported = false;

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
        measuredRefreshHz = ((REFRESH_MEASURE_FRAMES - 1) / span) * 1000;
        measurementReported = true;
        onRefreshRateMeasured?.(measuredRefreshHz);
      }

      const elapsedSec = (timestamp - startTime) / 1000;
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      const n = tiles.length;
      const cols = Math.ceil(Math.sqrt(n));
      const rows = Math.ceil(n / cols);
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

        // Sign(sin(2*pi*f*t)) on/off, derived from real elapsed time rather
        // than an integer frame-period divisor -- robust to a display that
        // isn't exactly 60Hz.
        const on = Math.sin(2 * Math.PI * tile.freqHz * elapsedSec) >= 0;

        ctx.fillStyle = on ? tile.color : "#111318";
        ctx.fillRect(x, y, w, h);

        if (tile.id === highlightedTileId) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = Math.max(4, w * 0.02);
          ctx.strokeRect(x, y, w, h);
        }

        ctx.fillStyle = on ? "#111318" : "#e8e8e8";
        ctx.font = `${Math.round(h * 0.12)}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(tile.label, x + w / 2, y + h / 2);
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tiles, highlightedTileId]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}
