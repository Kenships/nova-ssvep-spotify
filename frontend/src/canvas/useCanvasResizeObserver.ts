import { useEffect, type RefObject } from "react";

/**
 * Keeps a canvas's drawing-buffer resolution (canvas.width/height, in
 * device pixels) in sync with its CSS box size, via ResizeObserver rather
 * than a window "resize" listener -- window resize misses layout-only size
 * changes (e.g. a sidebar opening/closing via a CSS width transition, with
 * the window itself never resizing). Without this, a canvas's buffer stays
 * sized for whatever its CSS box was at the last resize event while the box
 * itself changes, so the browser stretches the old bitmap to fit the new
 * box -- squishing/stretching everything drawn on it.
 *
 * Calls `onResize` once on mount and again after every subsequent layout
 * resize, once canvas.width/height have already been updated -- callers
 * that don't run their own continuous draw loop (e.g. a canvas redrawn only
 * on data updates) should redraw inside it; a canvas driven by its own
 * requestAnimationFrame loop can omit it, since that loop already reads the
 * current canvas.width/height every frame.
 */
export function useCanvasResizeObserver(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  onResize?: () => void,
) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      onResize?.();
    };
    resize();

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasRef]);
}
