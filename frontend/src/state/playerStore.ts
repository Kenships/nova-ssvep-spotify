import { create } from "zustand";

export type Layer = "mood" | "transport";
export type WsStatus = "connecting" | "connected" | "disconnected";

interface NowPlaying {
  track: string;
  artist: string;
  album_art_url: string | null;
  is_playing: boolean;
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

  setLayer: (layer: Layer) => void;
  setCurrentMood: (moodId: string) => void;
  setWsStatus: (status: WsStatus) => void;
  setLastFired: (tileId: string) => void;
  setDetection: (label: string | null, confidence: number) => void;
  setNowPlaying: (np: NowPlaying | null) => void;
  setMeasuredRefreshHz: (hz: number) => void;
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

  setLayer: (layer) => set({ layer }),
  setCurrentMood: (moodId) => set({ currentMoodId: moodId }),
  setWsStatus: (status) => set({ wsStatus: status }),
  setLastFired: (tileId) => set({ lastFiredTileId: tileId }),
  setDetection: (label, confidence) => set({ detectedLabel: label, detectionConfidence: confidence }),
  setNowPlaying: (np) => set({ nowPlaying: np }),
  setMeasuredRefreshHz: (hz) => set({ measuredRefreshHz: hz }),
}));
