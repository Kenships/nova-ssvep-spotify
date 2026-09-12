import { useCallback, useState } from "react";
import { CalibrationScreen } from "./calibration/CalibrationScreen";
import { DebugPanelContent, DebugPanelToggle } from "./debug/DebugPanel";
import { DetectionQueue } from "./detections/DetectionQueue";
import { LSLSourcePanel } from "./lsl/LSLSourcePanel";
import { MoodLayer } from "./layers/MoodLayer";
import { TransportLayer } from "./layers/TransportLayer";
import { SettingsMenu } from "./settings/SettingsMenu";
import { labelForTileId } from "./ssvep/frequencies";
import { NowPlayingPanel } from "./spotify/nowPlayingPanel";
import { usePlayerStore } from "./state/playerStore";
import { useCommandSocket } from "./ws/useCommandSocket";

export function App() {
  const calibrationActive = usePlayerStore((s) => s.calibrationActive);
  const serverStateReady = usePlayerStore((s) => s.serverStateReady);
  const [calibrationBusy, setCalibrationBusy] = useState(false);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const layer = usePlayerStore((s) => s.layer);
  const currentMoodId = usePlayerStore((s) => s.currentMoodId);
  const setLastFired = usePlayerStore((s) => s.setLastFired);
  const wsStatus = usePlayerStore((s) => s.wsStatus);
  const detectedLabel = usePlayerStore((s) => s.detectedLabel);
  const detectionConfidence = usePlayerStore((s) => s.detectionConfidence);
  const lastFiredTileId = usePlayerStore((s) => s.lastFiredTileId);
  const flickerMode = usePlayerStore((s) => s.flickerMode);
  const streamWarning = usePlayerStore((s) => s.streamWarning);

  useCommandSocket(
    useCallback(
      (msg) => {
        setLastFired(msg.target);
      },
      [setLastFired],
    ),
  );

  // Tiles are always clickable, regardless of flicker mode or SSVEP signal
  // quality: routes through the same backend command_bus / Spotify path a
  // real detection would, so behavior is identical either way. The
  // resulting "command" broadcast (via useCommandSocket above) is what
  // actually updates local state -- this call doesn't touch state itself.
  const handleTileActivate = useCallback(async (tileId: string): Promise<boolean> => {
    try {
      const res = await fetch("/api/manual-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: tileId }),
      });
      if (!res.ok) {
        console.error("Manual command rejected:", await res.text());
        return false;
      }
      return true;
    } catch (err) {
      console.error("Manual command failed:", err);
      return false;
    }
  }, []);

  const changeCalibration = async (active: boolean) => {
    setCalibrationBusy(true);
    setCalibrationError(null);
    try {
      const res = await fetch("/api/calibration/session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active }),
      });
      if (!res.ok) throw new Error("Could not change calibration mode. Please retry.");
      // State arrives on the ordered WebSocket stream, including after reconnect.
    } catch {
      setCalibrationError("Could not change calibration mode. Check the backend connection and retry.");
    } finally {
      setCalibrationBusy(false);
    }
  };

  if (!serverStateReady) return <div className="app">Connecting to player...</div>;

  if (calibrationActive) {
    return <CalibrationScreen
      busy={calibrationBusy}
      error={calibrationError}
      onDone={() => { if (!calibrationBusy) void changeCalibration(false); }}
    />;
  }

  return (
    <div className="app-shell">
      <div className="app">
        <header className="app__header">
          <div className="app__title">♫ SSVEP Player</div>
          <nav className="app__breadcrumb">
            <span className={layer === "mood" ? "app__breadcrumb-step app__breadcrumb-step--active" : "app__breadcrumb-step"}>
              Playlists
            </span>
            <span className="app__breadcrumb-sep">›</span>
            <span className={layer === "transport" ? "app__breadcrumb-step app__breadcrumb-step--active" : "app__breadcrumb-step"}>
              Playback
            </span>
          </nav>
          {currentMoodId && (
            <div className="app__current-mood" title="Mood currently playing">
              ♪ {labelForTileId(currentMoodId)}
            </div>
          )}
          <button className="app__calibrate-btn" disabled={calibrationBusy} onClick={() => void changeCalibration(true)}>
            Run Calibration
          </button>
          <LSLSourcePanel />
          <SettingsMenu />
          <DebugPanelToggle />
          <div className={`app__ws-status app__ws-status--${wsStatus}`}>{wsStatus}</div>
        </header>

        {calibrationError && <p role="alert">{calibrationError}</p>}
        {streamWarning && <div className="app__stream-warning">⚠ {streamWarning}</div>}

        <div className="app__detections-bar">
          <DetectionQueue />
        </div>

        <main className="app__stage">
          {layer === "mood" ? (
            <MoodLayer highlightedTileId={lastFiredTileId} mode={flickerMode} onTileActivate={handleTileActivate} />
          ) : (
            <TransportLayer highlightedTileId={lastFiredTileId} mode={flickerMode} onTileActivate={handleTileActivate} />
          )}
        </main>

        <div className="app__now-playing-bar">
          <NowPlayingPanel />
        </div>

        <footer className="app__debug">
          detected: {detectedLabel ?? "—"} (confidence {detectionConfidence.toFixed(2)}) · layer: {layer}
        </footer>
      </div>

      <DebugPanelContent />
    </div>
  );
}
