export interface SnrReading {
  label: string;
  ready: boolean;
  snr: number;
  ok: boolean;
}

export interface CueUpdate {
  secondsLeft: number;
  reading: SnrReading | null;
  message: string | null;
}

const POLL_MS = 750;
const REQUEST_TIMEOUT_MS = 1500;
const MAX_READING_AGE_MS = POLL_MS + REQUEST_TIMEOUT_MS;

/** One target's acquisition. Requests never overlap, and failed/stale
 * readings cannot survive into the final result or the next target. */
export function runCalibrationCue(
  label: string,
  windowSec: number,
  onUpdate: (update: CueUpdate) => void,
  onComplete: (reading: SnrReading | null) => void,
): () => void {
  const started = performance.now();
  const settleMs = windowSec * 1000;
  const durationMs = Math.max(8000, settleMs + 4000);
  let cancelled = false;
  let latest: SnrReading | null = null;
  let receivedAt = 0;
  let message: string | null = "Collecting a fresh EEG window...";
  let request: AbortController | null = null;
  let pollTimer: ReturnType<typeof setTimeout>;
  let requestTimer: ReturnType<typeof setTimeout> | undefined;

  const freshReading = () => latest && performance.now() - receivedAt <= MAX_READING_AGE_MS ? latest : null;
  const update = () => onUpdate({
    secondsLeft: Math.max(0, Math.ceil((durationMs - (performance.now() - started)) / 1000)),
    reading: freshReading(), message,
  });
  const poll = async () => {
    request = new AbortController();
    requestTimer = setTimeout(() => request?.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(`/api/calibration/snr?label=${encodeURIComponent(label)}`, { signal: request.signal });
      if (!res.ok) throw new Error("Could not read EEG data. Check the connection.");
      const data: SnrReading = await res.json();
      if (data.label !== label || typeof data.ready !== "boolean" || typeof data.ok !== "boolean" || !Number.isFinite(data.snr)) {
        throw new Error("Invalid EEG response. Retry the check.");
      }
      if (cancelled) return;
      latest = data.ready ? data : null;
      receivedAt = performance.now();
      message = data.ready ? null : "Waiting for EEG data. Check the input source.";
    } catch {
      if (cancelled) return;
      latest = null;
      message = "Could not read EEG data. Check the connection.";
    } finally {
      clearTimeout(requestTimer);
      if (!cancelled) {
        update();
        pollTimer = setTimeout(poll, POLL_MS);
      }
    }
  };

  update();
  pollTimer = setTimeout(poll, settleMs);
  const countdown = setInterval(update, 250);
  const finish = setTimeout(() => {
    const result = freshReading();
    stop();
    onComplete(result);
  }, durationMs);
  function stop() {
    cancelled = true;
    clearTimeout(pollTimer);
    clearTimeout(requestTimer);
    clearInterval(countdown);
    clearTimeout(finish);
    request?.abort();
  }
  return stop;
}
