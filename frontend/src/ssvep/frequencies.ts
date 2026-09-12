// Experimental targets; keep synchronized with backend/app/config.py.
// Improved idle rejection has not been established by matched recordings.
// Elapsed-time rendering samples the stimulus at the display refresh rate;
// actual presentation timing still needs validation on the target display.
// Fractions of the canvas (0..1). When a tile set provides these, FlickerCanvas
// lays tiles out at these exact rects instead of its default auto square grid.
export interface TileRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FreqTile {
  id: string;
  label: string;
  freqHz: number;
  color: string;
  rect?: TileRect;
}

export const MOOD_TILES: FreqTile[] = [
  { id: "calm", label: "Calm", freqHz: 15.0, color: "#00F5FF" },
  { id: "happy", label: "Happy", freqHz: 16.5, color: "#DFFF00" },
  { id: "energetic", label: "Energetic", freqHz: 18.0, color: "#FF5F1F" },
  { id: "sad", label: "Sad", freqHz: 19.5, color: "#FF00FF" },
];

// Generic 2x2 grid, same as MOOD_TILES -- no explicit rect, so FlickerCanvas
// falls back to its auto square grid layout.
export const TRANSPORT_TILES: FreqTile[] = [
  { id: "previous", label: "⏮  Previous", freqHz: 18.0, color: "#FF5F1F" },
  { id: "play_pause", label: "⏯  Play / Pause", freqHz: 15.0, color: "#00F5FF" },
  { id: "next", label: "⏭  Next", freqHz: 16.5, color: "#DFFF00" },
  { id: "back_to_mood", label: "↩  Back to Playlists", freqHz: 19.5, color: "#FF00FF" },
];

/**
 * Given a real measured display refresh rate, compute the nearest integer
 * frame-period for a target frequency so flicker stays drift-free even if
 * the panel isn't exactly 60Hz.
 */
export function framePeriodFor(freqHz: number, measuredRefreshHz: number): number {
  return Math.max(1, Math.round(measuredRefreshHz / freqHz));
}

const ALL_TILES = [...MOOD_TILES, ...TRANSPORT_TILES];

/** Human-readable label for a mood or transport tile id, e.g. for display
 * in the current-mood title or the recent-detections queue. */
export function labelForTileId(id: string): string {
  return ALL_TILES.find((t) => t.id === id)?.label ?? id;
}
