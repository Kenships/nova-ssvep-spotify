import { useEffect, useRef, useState } from "react";

import type { LSLStatus } from "./types";

interface DiscoveredStream {
  name: string;
  type: string;
  channel_count: number;
  nominal_srate: number;
  hostname: string;
}

/** Openable panel to view and change the backend's LSL input source --
 * confirms what's actually connected (not just what was requested) by
 * polling /api/lsl/status after any switch, since a switch can fail to
 * find the target stream and leave the backend disconnected entirely (see
 * LSLIngest.switch_stream's docstring). Also scans the network for
 * available streams via /api/lsl/discover so switching doesn't require
 * already knowing the exact stream name.
 */
export function LSLSourcePanel() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<LSLStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredStream[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [manualName, setManualName] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  const refreshStatus = async () => {
    try {
      const res = await fetch("/api/lsl/status");
      if (!res.ok) throw new Error(`status ${res.status}`);
      setStatus(await res.json());
      setStatusError(null);
    } catch {
      setStatusError("Could not reach backend");
    }
  };

  useEffect(() => {
    if (!open) return;
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

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

  const scan = async () => {
    setScanning(true);
    try {
      const res = await fetch("/api/lsl/discover");
      const data: { streams: DiscoveredStream[] } = await res.json();
      setDiscovered(data.streams);
    } catch {
      setDiscovered([]);
    } finally {
      setScanning(false);
    }
  };

  const switchTo = async (streamName: string) => {
    if (!streamName.trim()) return;
    setSwitching(streamName);
    setSwitchError(null);
    try {
      const res = await fetch("/api/lsl/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream_name: streamName }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setSwitchError(body.detail ?? `Backend rejected the switch (${res.status})`);
      }
    } catch {
      setSwitchError("Could not reach backend");
    } finally {
      setSwitching(null);
      // Confirm what's actually connected now, regardless of whether the
      // switch itself reported success -- a failed switch still changes
      // state (it disconnects from the old stream; see backend docstring).
      await refreshStatus();
    }
  };

  return (
    <div className="lsl-source-panel" ref={containerRef}>
      <button
        className={`lsl-source-panel__trigger ${status?.connected ? "lsl-source-panel__trigger--connected" : "lsl-source-panel__trigger--disconnected"}`}
        onClick={() => setOpen((o) => !o)}
        aria-label="Input source"
        aria-expanded={open}
        title={status ? `${status.stream_name} (${status.connected ? "connected" : "disconnected"})` : "Input source"}
      >
        📡
      </button>
      {open && (
        <div className="lsl-source-panel__popover">
          <div className="lsl-source-panel__title">Input Source</div>

          {statusError && <div className="lsl-source-panel__error">{statusError}</div>}
          {status && (
            <div className="lsl-source-panel__status">
              <div className={`lsl-source-panel__badge ${status.connected ? "lsl-source-panel__badge--connected" : "lsl-source-panel__badge--disconnected"}`}>
                {status.connected ? "Connected" : "Disconnected"}
              </div>
              <div className="lsl-source-panel__status-name">{status.stream_name}</div>
              {status.connected && (
                <div className="lsl-source-panel__status-detail">
                  {status.fs}Hz · {status.channel_count}ch · host: {status.hostname}
                  <div>Selected stream channels: {status.occipital_indices.map((index) => index + 1).join(", ")}</div>
                  <div>Zero-based indices: {status.occipital_indices.join(", ")}</div>
                </div>
              )}
            </div>
          )}

          <button className="lsl-source-panel__scan-btn" onClick={scan} disabled={scanning}>
            {scanning ? "Scanning…" : "Scan for streams"}
          </button>

          {discovered !== null && (
            <div className="lsl-source-panel__discovered">
              {discovered.length === 0 ? (
                <div className="lsl-source-panel__empty">No streams found on the network</div>
              ) : (
                discovered.map((s) => (
                  <button
                    key={s.name}
                    className="lsl-source-panel__discovered-item"
                    onClick={() => switchTo(s.name)}
                    disabled={switching !== null}
                  >
                    <span className="lsl-source-panel__discovered-name">{s.name}</span>
                    <span className="lsl-source-panel__discovered-detail">
                      {s.nominal_srate}Hz · {s.channel_count}ch · {s.hostname}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}

          <div className="lsl-source-panel__manual">
            <input
              type="text"
              placeholder="Or type an exact stream name"
              value={manualName}
              onChange={(e) => setManualName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && switchTo(manualName)}
            />
            <button onClick={() => switchTo(manualName)} disabled={switching !== null || !manualName.trim()}>
              Connect
            </button>
          </div>

          {switching && <div className="lsl-source-panel__switching">Switching to {switching}…</div>}
          {switchError && <div className="lsl-source-panel__error">{switchError}</div>}
        </div>
      )}
    </div>
  );
}
