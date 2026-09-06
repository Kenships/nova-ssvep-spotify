// Collision-free SSVEP frequency set for a 60Hz display (integer frame
// periods, no drift). Must stay in sync with backend/app/config.py's
// mood_frequencies / transport_frequencies.
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
  { id: "calm", label: "Calm", freqHz: 7.5, color: "#4FC3F7" },
  { id: "happy", label: "Happy", freqHz: 60 / 7, color: "#FFD54F" },
  { id: "energetic", label: "Energetic", freqHz: 10.0, color: "#FF7043" },
  { id: "sad", label: "Sad", freqHz: 12.0, color: "#7986CB" },
];

// Laid out like a real media player: Previous/Play-Pause/Next in a row with
// Play/Pause widened and centered between the other two, Back to Playlists
// as a footer strip underneath -- rather than the generic 2x2 grid.
export const TRANSPORT_TILES: FreqTile[] = [
  { id: "previous", label: "⏮  Previous", freqHz: 10.0, color: "#FF7043", rect: { x: 0.0, y: 0.0, w: 0.29, h: 0.72 } },
  { id: "play_pause", label: "⏯  Play / Pause", freqHz: 7.5, color: "#4FC3F7", rect: { x: 0.31, y: 0.0, w: 0.38, h: 0.72 } },
  { id: "next", label: "⏭  Next", freqHz: 60 / 7, color: "#FFD54F", rect: { x: 0.71, y: 0.0, w: 0.29, h: 0.72 } },
  { id: "back_to_mood", label: "↩  Back to Playlists", freqHz: 12.0, color: "#7986CB", rect: { x: 0.0, y: 0.76, w: 1.0, h: 0.24 } },
];

/**
 * Given a real measured display refresh rate, compute the nearest integer
 * frame-period for a target frequency so flicker stays drift-free even if
 * the panel isn't exactly 60Hz.
 */
export function framePeriodFor(freqHz: number, measuredRefreshHz: number): number {
  return Math.max(1, Math.round(measuredRefreshHz / freqHz));
}
