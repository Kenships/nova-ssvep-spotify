import { useEffect, useState } from "react";
import type { LSLStatus } from "../lsl/types";

/** Mounted only while the debug panel is open. Poll the actual inlet so
 * source switches and EEG disconnections are reflected independently of WS. */
export function ConnectedDevice() {
  const [status, setStatus] = useState<LSLStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let nextPoll: ReturnType<typeof setTimeout>;
    let request: AbortController | null = null;
    let requestTimeout: ReturnType<typeof setTimeout>;
    const poll = async () => {
      request = new AbortController();
      requestTimeout = setTimeout(() => request?.abort(), 3000);
      try {
        const response = await fetch("/api/lsl/status", { signal: request.signal });
        if (!response.ok) throw new Error("Source status unavailable");
        const data: LSLStatus = await response.json();
        if (!cancelled) {
          setStatus(data);
          setError(false);
        }
      } catch {
        if (!cancelled) {
          setStatus(null);
          setError(true);
        }
      } finally {
        clearTimeout(requestTimeout);
        if (!cancelled) nextPoll = setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(nextPoll);
      clearTimeout(requestTimeout);
      request?.abort();
    };
  }, []);

  if (error) return <div className="debug-panel__empty" role="status">Device status unavailable. Retrying...</div>;
  if (!status) return <div className="debug-panel__empty">Checking connected device...</div>;

  return <div className="debug-panel__device">
    <span className={`debug-panel__device-status${status.connected ? " debug-panel__device-status--connected" : ""}`} role="status">
      {status.connected ? "Connected" : "Disconnected"}
    </span>
    <div className="debug-panel__device-name">{status.stream_name || "No source selected"}</div>
    {status.connected && <dl className="debug-panel__device-details">
      <dt>Host</dt><dd>{status.hostname || "Unknown"}</dd>
      <dt>Sample rate</dt><dd>{status.fs} Hz</dd>
      <dt>Stream channels</dt><dd>{status.channel_count}</dd>
      <dt>Selected channels</dt><dd>{status.occipital_indices.map((index) => index + 1).join(", ") || "None"}</dd>
      <dt>Zero-based indices</dt><dd>{status.occipital_indices.join(", ") || "None"}</dd>
    </dl>}
  </div>;
}
