// Collision-free SSVEP frequency set for a 60Hz display (integer frame
// periods, no drift). Must stay in sync with backend/app/config.py's
// mood_frequencies / transport_frequencies.
export interface FreqTile {
  id: string;
  label: string;
  freqHz: number;
  color: string;
}

export const MOOD_TILES: FreqTile[] = [
  { id: "calm", label: "Calm", freqHz: 7.5, color: "#4FC3F7" },
  { id: "happy", label: "Happy", freqHz: 60 / 7, color: "#FFD54F" },
  { id: "energetic", label: "Energetic", freqHz: 10.0, color: "#FF7043" },
  { id: "sad", label: "Sad", freqHz: 12.0, color: "#7986CB" },
];

export const TRANSPORT_TILES: FreqTile[] = [
  { id: "play_pause", label: "Play / Pause", freqHz: 7.5, color: "#4FC3F7" },
  { id: "next", label: "Next", freqHz: 60 / 7, color: "#FFD54F" },
  { id: "previous", label: "Previous", freqHz: 10.0, color: "#FF7043" },
  { id: "back_to_mood", label: "Change Mood", freqHz: 12.0, color: "#7986CB" },
];

/**
 * Given a real measured display refresh rate, compute the nearest integer
 * frame-period for a target frequency so flicker stays drift-free even if
 * the panel isn't exactly 60Hz.
 */
export function framePeriodFor(freqHz: number, measuredRefreshHz: number): number {
  return Math.max(1, Math.round(measuredRefreshHz / freqHz));
}
