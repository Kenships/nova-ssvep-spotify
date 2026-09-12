import { useEffect, useMemo, useRef, useState } from "react";
import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import { MOOD_TILES } from "../ssvep/frequencies";
import { usePlayerStore } from "../state/playerStore";
import { runCalibrationCue, type CueUpdate, type SnrReading } from "./runCalibrationCue";

interface CalibrationScreenProps {
  onDone: () => void;
  busy?: boolean;
  error?: string | null;
}
interface StepResult {
  moodId: string;
  reading: SnrReading | null;
}

function describeQuality(reading: SnrReading | null, threshold: number) {
  if (!reading) return { text: "No data captured", tier: "none" };
  return reading.snr >= threshold
    ? { text: "Above SNR threshold", tier: "good" }
    : { text: "Below SNR threshold", tier: "weak" };
}

/** Guided signal check; its display cutoff does not change the detector. */
export function CalibrationScreen({ onDone, busy = false, error = null }: CalibrationScreenProps) {
  const [snrThreshold, setSnrThreshold] = useState(2.0);
  const [stepIndex, setStepIndex] = useState(-1);
  const [windowSec, setWindowSec] = useState(0);
  const [loading, setLoading] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [update, setUpdate] = useState<CueUpdate>({ secondsLeft: 0, reading: null, message: null });
  const [results, setResults] = useState<StepResult[]>([]);
  const flickerMode = usePlayerStore((s) => s.flickerMode);
  const setFlickerMode = usePlayerStore((s) => s.setFlickerMode);
  const startRequest = useRef<AbortController | null>(null);
  const currentTile = MOOD_TILES[stepIndex];
  // Keep this array stable through countdown/SNR updates: changing its
  // identity restarts FlickerCanvas's animation and resets stimulus phase.
  const tiles = useMemo(() => currentTile ? [currentTile] : [], [currentTile]);
  const complete = stepIndex >= MOOD_TILES.length;

  useEffect(() => () => startRequest.current?.abort(), []);

  const start = async () => {
    setLoading(true);
    setStartError(null);
    const controller = new AbortController();
    startRequest.current = controller;
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch("/api/config/detection", { signal: controller.signal });
      if (!res.ok) throw new Error("Configuration unavailable");
      const config = await res.json();
      if (!Number.isFinite(config.window_sec) || config.window_sec <= 0) throw new Error("Invalid window duration");
      setWindowSec(config.window_sec);
      setResults([]);
      setStepIndex(0);
    } catch {
      setStartError("Could not load the EEG settings. Check the connection and retry.");
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!currentTile || flickerMode === "off") return;
    return runCalibrationCue(currentTile.id, windowSec, setUpdate, (reading) => {
      setResults((previous) => [...previous, { moodId: currentTile.id, reading }]);
      setStepIndex((index) => index + 1);
    });
  }, [currentTile, windowSec, flickerMode]);

  const quality = describeQuality(update.reading, snrThreshold);
  const passed = results.filter((r) => r.reading && r.reading.snr >= snrThreshold).length;
  return (
    <main className="calibration-screen">
      <header className="calibration-screen__header">
        <div>
          <h1 className="calibration-screen__title">{complete ? "Signal check complete" : "Calibration: signal check"}</h1>
          <p className="calibration-screen__description">Playback commands are paused until you return to the player.</p>
        </div>
        <button className="calibration-screen__secondary-btn" disabled={busy} onClick={onDone}>
          {busy ? "Returning..." : "Exit calibration"}
        </button>
      </header>
      {(error || startError) && <p role="alert" className="calibration-screen__error">{error || startError}</p>}

      <div className="calibration-screen__cutoff">
        <label htmlFor="calibration-snr-cutoff">Signal-check cutoff: <output>{snrThreshold.toFixed(1)}</output> SNR</label>
        <input id="calibration-snr-cutoff" type="range" min="1" max="6" step="0.1" value={snrThreshold}
          onChange={(event) => setSnrThreshold(Number(event.target.value))} />
        <p>Adjusts these result labels only. Lower values are easier to pass; this trial cutoff is not a validated personal calibration.</p>
      </div>

      {stepIndex === -1 ? (
        <section className="calibration-screen__intro">
          <h2>Check each target before playing</h2>
          <p>Look at each tile while it flashes. We measure signal strength at its frequency and show the result for all four targets.</p>
          <p>This check does not change the detector or save calibration settings.</p>
          {flickerMode === "off" && <p>Flicker is off. Enable Soft Pulse to run the check, or return to the player for manual control.</p>}
          {flickerMode === "off" ? (
            <button className="calibration-screen__continue-btn" disabled={busy} onClick={() => setFlickerMode("sine")}>Enable Soft Pulse</button>
          ) : (
            <button className="calibration-screen__continue-btn" disabled={loading || busy} onClick={() => void start()}>
              {loading ? "Loading EEG settings..." : "Start signal check"}
            </button>
          )}
        </section>
      ) : complete ? (
        <>
          <p role="status">{passed} of {MOOD_TILES.length} targets above the SNR threshold.</p>
          <div className="calibration-screen__summary">
            {results.map((result) => {
              const tile = MOOD_TILES.find((t) => t.id === result.moodId)!;
              const resultQuality = describeQuality(result.reading, snrThreshold);
              return <div key={result.moodId} className="calibration-screen__summary-row">
                <span className="calibration-screen__summary-label">{tile.label} <small>{tile.freqHz} Hz</small></span>
                <span className={`calibration-screen__quality calibration-screen__quality--${resultQuality.tier}`}>{resultQuality.text}</span>
                <span className="calibration-screen__summary-snr">SNR {result.reading ? result.reading.snr.toFixed(1) : "--"}</span>
              </div>;
            })}
          </div>
          <p className="calibration-screen__description">Results show the latest available reading for each target. They do not establish detection accuracy.</p>
          <div className="calibration-screen__actions">
            <button className="calibration-screen__secondary-btn" disabled={busy} onClick={() => setStepIndex(-1)}>Run again</button>
            <button className="calibration-screen__continue-btn" disabled={busy} onClick={onDone}>{busy ? "Returning..." : "Continue to Player"}</button>
          </div>
        </>
      ) : (
        <>
          <div className="calibration-screen__step-label">Target {stepIndex + 1} of {MOOD_TILES.length}: <strong>{currentTile.label}</strong> ({currentTile.freqHz} Hz)</div>
          <div className="calibration-screen__instructions">Look at the flashing tile ({update.secondsLeft}s)</div>
          <div className="calibration-screen__stage"><FlickerCanvas tiles={tiles} highlightedTileId={null} mode={flickerMode} /></div>
          <div role="status" className={`calibration-screen__quality calibration-screen__quality--${update.reading ? quality.tier : "pending"}`}>
            {update.message ?? quality.text}
            {update.reading && <span className="calibration-screen__snr-value"> (SNR {update.reading.snr.toFixed(1)})</span>}
          </div>
          <div className="calibration-screen__progress-dots" aria-label={`Target ${stepIndex + 1} of ${MOOD_TILES.length}`}>
            {MOOD_TILES.map((tile, index) => <div key={tile.id} title={tile.label} className={`calibration-screen__dot${index === stepIndex ? " calibration-screen__dot--current" : results[index] ? (results[index].reading && results[index].reading!.snr >= snrThreshold) ? " calibration-screen__dot--ok" : " calibration-screen__dot--weak" : ""}`} />)}
          </div>
        </>
      )}
    </main>
  );
}
