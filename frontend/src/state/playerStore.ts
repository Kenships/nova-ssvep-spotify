import { create } from "zustand";
import type { FlickerMode } from "../ssvep/flickerModes";

export type Layer = "mood" | "transport";
export type WsStatus = "connecting" | "connected" | "disconnected";

const FLICKER_MODE_STORAGE_KEY = "ssvep-flicker-mode";
const REFRACTORY_FEEDBACK_STORAGE_KEY = "ssvep-refractory-feedback-enabled";

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

function loadStoredRefractoryFeedbackEnabled(): boolean {
  try {
    const stored = localStorage.getItem(REFRACTORY_FEEDBACK_STORAGE_KEY);
    if (stored !== null) return stored === "true";
  } catch {
    // localStorage unavailable (private browsing, etc.) -- fall through to default.
  }
  return true;
}

export interface DetectionEvent {
  label: string;
  layer: Layer;
  timestamp: number;
}

const MAX_DETECTION_HISTORY = 8;

export interface RawChannelData {
  fs: number;
  channelLabels: string[];
  /** (n_samples, n_channels), oldest first. */
  samples: number[][];
}

interface NowPlaying {
  track: string;
  artist: string;
  album_art_url: string | null;
  is_playing: boolean;
  progress_ms: number;
  duration_ms: number;
}

export interface ServerPlayerState {
  layer: Layer;
  currentMoodId: string | null;
  calibrationActive: boolean;
}

interface PlayerState {
  calibrationActive: boolean;
  serverStateReady: boolean;
  setServerState: (state: ServerPlayerState) => void;
  layer: Layer;
  currentMoodId: string | null;
  wsStatus: WsStatus;
  lastFiredTileId: string | null;
  detectedLabel: string | null;
  detectionConfidence: number;
  /** Every candidate frequency's confidence for the most recent detector
   * tick, not just the winner's -- keyed by mood/transport tile id. */
  detectionScores: Record<string, number>;
  nowPlaying: NowPlaying | null;
  measuredRefreshHz: number | null;
  flickerMode: FlickerMode;
  /** Per-viewer display preference (localStorage, not backend state): while
   * true, a fired input is shown large and centered -- tiles hidden -- for
   * the backend's refractory period that follows it. */
  refractoryFeedbackEnabled: boolean;
  /** Set from a backend {"type":"error"} WS message (e.g. the EEG/LSL stream
   * dropping out mid-session); cleared by the matching {"type":"info"}
   * once it recovers. Null means nothing to warn about. */
  streamWarning: string | null;
  /** Most recent registered inputs (fired commands), newest first -- distinct
   * from detectedLabel/detectionConfidence, which reflect every raw detector
   * tick regardless of whether it ever passed dwell/debounce to fire. */
  detectionHistory: DetectionEvent[];
  /** Open/closed state of the debug side panel (raw channel graph +
   * per-frequency confidence). Read by useCommandSocket to know whether to
   * (re-)send raw_subscribe after connecting. */
  debugPanelOpen: boolean;
  /** Most recent raw occipital-channel snapshot for the debug panel's live
   * graph; null until the panel has been opened at least once this session. */
  rawChannelData: RawChannelData | null;
  /** Set by useCommandSocket once the WS is open; lets any component (the
   * debug panel toggle) (un)subscribe to raw channel data without prop
   * drilling the socket itself down to it. */
  sendRawSubscription: ((subscribe: boolean) => void) | null;

  setLayer: (layer: Layer) => void;
  setCurrentMood: (moodId: string) => void;
  setWsStatus: (status: WsStatus) => void;
  setLastFired: (tileId: string) => void;
  setDetection: (label: string | null, confidence: number, scores: Record<string, number>) => void;
  setNowPlaying: (np: NowPlaying | null) => void;
  setMeasuredRefreshHz: (hz: number) => void;
  setFlickerMode: (mode: FlickerMode) => void;
  setRefractoryFeedbackEnabled: (enabled: boolean) => void;
  setStreamWarning: (message: string | null) => void;
  addDetectionEvent: (label: string, layer: Layer) => void;
  setDebugPanelOpen: (open: boolean) => void;
  setRawChannelData: (data: RawChannelData) => void;
  setSendRawSubscription: (fn: ((subscribe: boolean) => void) | null) => void;
}

export const usePlayerStore = create<PlayerState>((set) => ({
  calibrationActive: false,
  serverStateReady: false,
  setServerState: (state) => set({ ...state, serverStateReady: true }),
  layer: "mood",
  currentMoodId: null,
  wsStatus: "connecting",
  lastFiredTileId: null,
  detectedLabel: null,
  detectionConfidence: 0,
  detectionScores: {},
  nowPlaying: null,
  measuredRefreshHz: null,
  flickerMode: loadStoredFlickerMode(),
  refractoryFeedbackEnabled: loadStoredRefractoryFeedbackEnabled(),
  streamWarning: null,
  detectionHistory: [],
  debugPanelOpen: false,
  rawChannelData: null,
  sendRawSubscription: null,

  setLayer: (layer) => set({ layer }),
  setCurrentMood: (moodId) => set({ currentMoodId: moodId }),
  setWsStatus: (status) => set(status === "connected" ? { wsStatus: status } : { wsStatus: status, serverStateReady: false }),
  setLastFired: (tileId) => set({ lastFiredTileId: tileId }),
  setDetection: (label, confidence, scores) =>
    set({ detectedLabel: label, detectionConfidence: confidence, detectionScores: scores }),
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
  setRefractoryFeedbackEnabled: (enabled) => {
    try {
      localStorage.setItem(REFRACTORY_FEEDBACK_STORAGE_KEY, String(enabled));
    } catch {
      // Best-effort persistence only -- a per-viewer convenience, not load-bearing.
    }
    set({ refractoryFeedbackEnabled: enabled });
  },
  setStreamWarning: (message) => set({ streamWarning: message }),
  addDetectionEvent: (label, layer) =>
    set((s) => ({
      detectionHistory: [{ label, layer, timestamp: Date.now() }, ...s.detectionHistory].slice(
        0,
        MAX_DETECTION_HISTORY,
      ),
    })),
  setDebugPanelOpen: (open) => set({ debugPanelOpen: open }),
  setRawChannelData: (data) => set({ rawChannelData: data }),
  setSendRawSubscription: (fn) => set({ sendRawSubscription: fn }),
}));
