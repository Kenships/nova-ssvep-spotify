import { useCallback, useState } from "react";
import { CalibrationScreen } from "./calibration/CalibrationScreen";
import { MoodLayer } from "./layers/MoodLayer";
import { TransportLayer } from "./layers/TransportLayer";
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

  if (screen === "calibration") {
    return <CalibrationScreen onDone={() => setScreen("player")} />;
  }

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__title">SSVEP Player</div>
        <NowPlayingPanel />
        <button className="app__calibrate-btn" onClick={() => setScreen("calibration")}>
          Run Calibration
        </button>
        <div className={`app__ws-status app__ws-status--${wsStatus}`}>{wsStatus}</div>
      </header>

      <main className="app__stage">
        {layer === "mood" ? (
          <MoodLayer highlightedTileId={lastFiredTileId} />
        ) : (
          <TransportLayer highlightedTileId={lastFiredTileId} />
        )}
      </main>

      <footer className="app__debug">
        detected: {detectedLabel ?? "—"} (confidence {detectionConfidence.toFixed(2)}) · layer: {layer}
      </footer>
    </div>
  );
}
