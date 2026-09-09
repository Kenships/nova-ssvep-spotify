import { useCallback, useState } from "react";
import { CalibrationScreen } from "./calibration/CalibrationScreen";
import { MoodLayer } from "./layers/MoodLayer";
import { TransportLayer } from "./layers/TransportLayer";
import { SettingsMenu } from "./settings/SettingsMenu";
import { NowPlayingPanel } from "./spotify/nowPlayingPanel";
import { usePlayerStore } from "./state/playerStore";
import { useCommandSocket } from "./ws/useCommandSocket";

type Screen = "calibration" | "player";

export function App() {
  const [screen, setScreen] = useState<Screen>("player");
  const layer = usePlayerStore((s) => s.layer);
  const setLayer = usePlayerStore((s) => s.setLayer);
  const setCurrentMood = usePlayerStore((s) => s.setCurrentMood);
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
        if (msg.layer === "mood") {
          setCurrentMood(msg.target);
          setLayer("transport");
        } else if (msg.target === "back_to_mood") {
          setLayer("mood");
        }
      },
      [setLastFired, setCurrentMood, setLayer],
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

  if (screen === "calibration") {
    return <CalibrationScreen onDone={() => setScreen("player")} />;
  }

  return (
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
        <button className="app__calibrate-btn" onClick={() => setScreen("calibration")}>
          Run Calibration
        </button>
        <SettingsMenu />
        <div className={`app__ws-status app__ws-status--${wsStatus}`}>{wsStatus}</div>
      </header>

      {streamWarning && <div className="app__stream-warning">⚠ {streamWarning}</div>}

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
  );
}
