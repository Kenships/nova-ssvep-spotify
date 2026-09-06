// Selectable stimulus rendering styles. Backed by research (see project
// notes): a hard 100%-depth color<->black square wave is more jarring than
// necessary without a real accuracy payoff -- a 2022 study found accuracy
// holds essentially flat down to ~50-60% modulation depth in our frequency
// range, and our detectors (PSDA/CCA keyed on fundamental + 2nd harmonic)
// don't depend on the extra odd harmonics a square wave adds over a sine.
//
// "rings" and "checkerboard"/"gabor" are pattern/geometry-based alternatives
// with independently-documented comfort benefits, included as selectable
// options rather than a single hardcoded choice since comfort/legibility
// preference is per-user. "off" disables all flicker for manual-only use.
export type FlickerMode = "sine" | "rings" | "checkerboard" | "gabor" | "off";

export interface FlickerModeOption {
  id: FlickerMode;
  label: string;
  description: string;
}

export const FLICKER_MODE_OPTIONS: FlickerModeOption[] = [
  {
    id: "sine",
    label: "Soft Pulse",
    description: "Smooth brightness pulse at ~55% depth. Best supported balance of comfort and accuracy.",
  },
  {
    id: "rings",
    label: "Concentric Rings",
    description: "Pulsing bullseye rings. Best measured resistance to visual fatigue over time.",
  },
  {
    id: "checkerboard",
    label: "Checkerboard",
    description: "Classic pattern-reversal -- constant mean brightness, only contrast flips.",
  },
  {
    id: "gabor",
    label: "Gabor Texture",
    description: "Reversing striped grating. Experimental -- comfort claims not independently verified yet.",
  },
  {
    id: "off",
    label: "Off (manual only)",
    description: "No flicker. Tiles stay static and are click/keyboard operated only.",
  },
];

export const SINE_MODULATION_DEPTH = 0.55;
