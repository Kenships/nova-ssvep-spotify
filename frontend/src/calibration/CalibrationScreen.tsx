import { useEffect, useState } from "react";
import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import { MOOD_TILES } from "../ssvep/frequencies";
import { usePlayerStore } from "../state/playerStore";

const CUE_DURATION_SEC = 8;

interface CalibrationScreenProps {
  onDone: () => void;
}

/**
 * UI shell for the ~30s per-session calibration sequence: cue the user
 * through each target in turn. Backend SNR computation
 * (backend/app/calibration.py) is not yet wired to an HTTP endpoint --
 * that's a Phase 3 TODO alongside the CCA upgrade. For now this validates
 * the cueing UX and gives the team something to run against the simulator
 * well before hardware day.
 */
export function CalibrationScreen({ onDone }: CalibrationScreenProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(CUE_DURATION_SEC);
  const flickerMode = usePlayerStore((s) => s.flickerMode);

  const currentTile = MOOD_TILES[stepIndex];

  useEffect(() => {
    if (stepIndex >= MOOD_TILES.length) {
      onDone();
      return;
    }
    setSecondsLeft(CUE_DURATION_SEC);
    const interval = setInterval(() => {
      setSecondsLeft((s) => s - 1);
    }, 1000);
    const timeout = setTimeout(() => {
      setStepIndex((i) => i + 1);
    }, CUE_DURATION_SEC * 1000);
    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [stepIndex, onDone]);

  if (!currentTile) return null;

  return (
    <div className="calibration-screen">
      <div className="calibration-screen__instructions">
        Look at the flashing <strong>{currentTile.label}</strong> tile ({secondsLeft}s)
      </div>
      <div className="calibration-screen__stage">
        <FlickerCanvas tiles={[currentTile]} highlightedTileId={null} mode={flickerMode} />
      </div>
      <div className="calibration-screen__progress">
        {stepIndex + 1} / {MOOD_TILES.length}
      </div>
    </div>
  );
}
