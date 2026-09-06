import { useEffect, useRef } from "react";
import { usePlayerStore } from "../state/playerStore";

type CommandMessage = { type: "command"; layer: "mood" | "transport"; target: string };
type DebugMessage = { type: "debug"; detectedLabel: string | null; confidence: number; layer: string };
type ServerMessage = CommandMessage | DebugMessage;

const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/commands`;
const RECONNECT_DELAY_MS = 1500;

/**
 * Owns the single persistent WebSocket to the backend. The frontend never
 * polls -- it only reacts to pushed command/debug events. Auto-reconnects
 * on drop so a transient backend restart (or LSL dropout mid-demo) doesn't
 * require a page reload.
 */
export function useCommandSocket(onCommand: (msg: CommandMessage) => void) {
  const setWsStatus = usePlayerStore((s) => s.setWsStatus);
  const setDetection = usePlayerStore((s) => s.setDetection);
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      setWsStatus("connecting");
      ws = new WebSocket(WS_URL);

      ws.onopen = () => setWsStatus("connected");

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data) as ServerMessage;
        if (msg.type === "debug") {
          setDetection(msg.detectedLabel, msg.confidence);
        } else if (msg.type === "command") {
          onCommandRef.current(msg);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
