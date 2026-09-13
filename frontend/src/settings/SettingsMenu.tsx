import { useEffect, useRef, useState } from "react";
import { FLICKER_MODE_OPTIONS } from "../ssvep/flickerModes";
import { usePlayerStore } from "../state/playerStore";

// Matches the dwell/refractory inputs' `min` attributes below -- kept as
// constants so the displayed floor and the actual validation can't drift apart.
const MIN_DWELL_SEC = 0.1;
const MIN_REFRACTORY_SEC = 0.1;

export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const flickerMode = usePlayerStore((s) => s.flickerMode);
  const setFlickerMode = usePlayerStore((s) => s.setFlickerMode);
  const refractoryFeedbackEnabled = usePlayerStore((s) => s.refractoryFeedbackEnabled);
  const setRefractoryFeedbackEnabled = usePlayerStore((s) => s.setRefractoryFeedbackEnabled);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Dwell time: how long a target must be continuously detected before it
  // registers as an input (backend's CommandBus.dwell_sec). Lives on the
  // backend, not localStorage -- it's part of the live detection pipeline,
  // not a per-viewer display preference, and hardware bring-up needs to
  // tune it live without a backend restart.
  const [confidenceInput, setConfidenceInput] = useState("");
  const [confidenceSaved, setConfidenceSaved] = useState<number | null>(null);
  const [confidenceError, setConfidenceError] = useState<string | null>(null);
  const [dwellInput, setDwellInput] = useState("");
  const [dwellSaved, setDwellSaved] = useState<number | null>(null);
  const [dwellError, setDwellError] = useState<string | null>(null);
  // Refractory time: how long detection pauses after a target fires
  // (backend's CommandBus.refractory_sec) -- also drives how long the
  // large-input-feedback overlay stays up, so it lives on the backend for
  // the same live-tuning reason as dwell above.
  const [refractoryInput, setRefractoryInput] = useState("");
  const [refractorySaved, setRefractorySaved] = useState<number | null>(null);
  const [refractoryError, setRefractoryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/config/detection")
      .then((res) => res.json())
      .then((data: { dwell_sec: number; confidence_threshold: number; refractory_sec: number }) => {
        if (cancelled) return;
        setDwellInput(String(data.dwell_sec));
        setDwellSaved(data.dwell_sec);
        setConfidenceInput(String(data.confidence_threshold));
        setConfidenceSaved(data.confidence_threshold);
        setRefractoryInput(String(data.refractory_sec));
        setRefractorySaved(data.refractory_sec);
      })
      .catch(() => {
        // Best-effort -- leave the field blank if the backend isn't reachable yet.
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const applyConfidence = async (input = confidenceInput) => {
    const value = Number(input);
    if (!Number.isFinite(value) || value <= 0 || value > 1) {
      setConfidenceError("Must be greater than 0 and at most 1");
      return;
    }
    try {
      const res = await fetch("/api/config/detection", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confidence_threshold: value }),
      });
      if (!res.ok) throw new Error("Rejected");
      const data: { confidence_threshold: number } = await res.json();
      setConfidenceInput(String(data.confidence_threshold));
      setConfidenceSaved(data.confidence_threshold);
      setConfidenceError(null);
    } catch {
      setConfidenceError("Could not update the detector threshold");
    }
  };

  const applyDwell = async () => {
    const value = parseFloat(dwellInput);
    if (!Number.isFinite(value) || value < MIN_DWELL_SEC) {
      setDwellError(`Must be at least ${MIN_DWELL_SEC}s`);
      return;
    }
    try {
      const res = await fetch("/api/config/detection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dwell_sec: value }),
      });
      if (!res.ok) {
        setDwellError("Backend rejected that value");
        return;
      }
      const data: { dwell_sec: number } = await res.json();
      setDwellSaved(data.dwell_sec);
      setDwellError(null);
    } catch {
      setDwellError("Could not reach backend");
    }
  };

  const applyRefractory = async () => {
    const value = parseFloat(refractoryInput);
    if (!Number.isFinite(value) || value < MIN_REFRACTORY_SEC) {
      setRefractoryError(`Must be at least ${MIN_REFRACTORY_SEC}s`);
      return;
    }
    try {
      const res = await fetch("/api/config/detection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refractory_sec: value }),
      });
      if (!res.ok) {
        setRefractoryError("Backend rejected that value");
        return;
      }
      const data: { refractory_sec: number } = await res.json();
      setRefractorySaved(data.refractory_sec);
      setRefractoryError(null);
    } catch {
      setRefractoryError("Could not reach backend");
    }
  };

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div className="settings-menu" ref={containerRef}>
      <button
        className="settings-menu__trigger"
        onClick={() => setOpen((o) => !o)}
        aria-label="Stimulus settings"
        aria-expanded={open}
      >
        ⚙
      </button>
      {open && (
        <div className="settings-menu__panel">
          <div className="settings-menu__title">Flicker Style</div>
          {FLICKER_MODE_OPTIONS.map((opt) => (
            <label key={opt.id} className="settings-menu__option">
              <input
                type="radio"
                name="flicker-mode"
                value={opt.id}
                checked={flickerMode === opt.id}
                onChange={() => setFlickerMode(opt.id)}
              />
              <div>
                <div className="settings-menu__option-label">{opt.label}</div>
                <div className="settings-menu__option-desc">{opt.description}</div>
              </div>
            </label>
          ))}
          <div className="settings-menu__title">Detection Sensitivity</div>
          <label className="settings-menu__field">
            <span>Confidence threshold: <output>{confidenceInput ? Number(confidenceInput).toFixed(2) : "Loading..."}</output></span>
            <input type="range" min={0.01} max={1} step={0.01} value={confidenceInput || 0.35}
              disabled={confidenceSaved === null}
              aria-valuetext={confidenceInput ? Number(confidenceInput).toFixed(2) : "Loading"}
              onChange={(event) => setConfidenceInput(event.target.value)}
              onPointerUp={(event) => void applyConfidence(event.currentTarget.value)}
              onKeyUp={(event) => void applyConfidence(event.currentTarget.value)}
              onBlur={(event) => void applyConfidence(event.currentTarget.value)} />
          </label>
          <div className="settings-menu__option-desc">
            Lower values accept weaker detections and may trigger more unwanted commands. Changes apply to this backend session.
            {confidenceSaved !== null && !confidenceError && ` Currently ${confidenceSaved.toFixed(2)}.`}
          </div>
          {confidenceError && <div className="settings-menu__error">{confidenceError}</div>}
          <div className="settings-menu__title">Input Timing</div>
          <label className="settings-menu__field">
            <span>Dwell time (seconds)</span>
            <input
              type="number"
              min={MIN_DWELL_SEC}
              step={0.05}
              value={dwellInput}
              onChange={(e) => setDwellInput(e.target.value)}
              onBlur={applyDwell}
            />
          </label>
          <div className="settings-menu__option-desc">
            How long a target must be continuously attended before it registers as an input.
            {dwellSaved !== null && !dwellError && ` Currently ${dwellSaved}s.`}
          </div>
          {dwellError && <div className="settings-menu__error">{dwellError}</div>}

          <label className="settings-menu__field">
            <span>Refractory period (seconds)</span>
            <input
              type="number"
              min={MIN_REFRACTORY_SEC}
              step={0.05}
              value={refractoryInput}
              onChange={(e) => setRefractoryInput(e.target.value)}
              onBlur={applyRefractory}
            />
          </label>
          <div className="settings-menu__option-desc">
            How long detection pauses after a target fires, before a new one can register.
            {refractorySaved !== null && !refractoryError && ` Currently ${refractorySaved}s.`}
          </div>
          {refractoryError && <div className="settings-menu__error">{refractoryError}</div>}

          <label className="settings-menu__option">
            <input
              type="checkbox"
              checked={refractoryFeedbackEnabled}
              onChange={(event) => setRefractoryFeedbackEnabled(event.target.checked)}
            />
            <div>
              <div className="settings-menu__option-label">Show input during refractory period</div>
              <div className="settings-menu__option-desc">
                Hides the tiles and shows the registered input large and centered until the refractory period ends.
              </div>
            </div>
          </label>

          <div className="settings-menu__footnote">Tiles are always clickable, in any mode.</div>
        </div>
      )}
    </div>
  );
}
