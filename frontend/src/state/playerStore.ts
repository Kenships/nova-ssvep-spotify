import { create } from "zustand";
import type { FlickerMode } from "../ssvep/flickerModes";

export type Layer = "mood" | "transport";
export type WsStatus = "connecting" | "connected" | "disconnected";

const FLICKER_MODE_STORAGE_KEY = "ssvep-flicker-mode";

function loadStoredFlickerMode(): FlickerMode {
  try {
    const stored = localStorage.getItem(FLICKER_MODE_STORAGE_KEY);
    if (stored === "sine" || stored === "rings" || stored === "checkerboard" || stored === "gabor" || stored === "off") {
      return stored;
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) -- fall through to default.
  }
  return "sine";
}

interface NowPlaying {
  track: string;
  artist: string;
  album_art_url: string | null;
  is_playing: boolean;
  progress_ms: number;
  duration_ms: number;
}

interface PlayerState {
  layer: Layer;
  currentMoodId: string | null;
  wsStatus: WsStatus;
  lastFiredTileId: string | null;
  detectedLabel: string | null;
  detectionConfidence: number;
  nowPlaying: NowPlaying | null;
  measuredRefreshHz: number | null;
  flickerMode: FlickerMode;

  setLayer: (layer: Layer) => void;
  setCurrentMood: (moodId: string) => void;
  setWsStatus: (status: WsStatus) => void;
  setLastFired: (tileId: string) => void;
  setDetection: (label: string | null, confidence: number) => void;
  setNowPlaying: (np: NowPlaying | null) => void;
  setMeasuredRefreshHz: (hz: number) => void;
  setFlickerMode: (mode: FlickerMode) => void;
}

export const usePlayerStore = create<PlayerState>((set) => ({
  layer: "mood",
  currentMoodId: null,
  wsStatus: "connecting",
  lastFiredTileId: null,
  detectedLabel: null,
  detectionConfidence: 0,
  nowPlaying: null,
  measuredRefreshHz: null,
  flickerMode: loadStoredFlickerMode(),

  setLayer: (layer) => set({ layer }),
  setCurrentMood: (moodId) => set({ currentMoodId: moodId }),
  setWsStatus: (status) => set({ wsStatus: status }),
  setLastFired: (tileId) => set({ lastFiredTileId: tileId }),
  setDetection: (label, confidence) => set({ detectedLabel: label, detectionConfidence: confidence }),
  setNowPlaying: (np) => set({ nowPlaying: np }),
  setMeasuredRefreshHz: (hz) => set({ measuredRefreshHz: hz }),
  setFlickerMode: (mode) => {
    try {
      localStorage.setItem(FLICKER_MODE_STORAGE_KEY, mode);
    } catch {
      // Best-effort persistence only -- a per-viewer convenience, not load-bearing.
    }
    set({ flickerMode: mode });
  },
}));
