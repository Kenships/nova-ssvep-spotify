import { useEffect, useRef } from "react";
import { usePlayerStore, type ServerPlayerState } from "../state/playerStore";

type CommandMessage = { type: "command"; layer: "mood" | "transport"; target: string; refractorySec: number };
type DebugMessage = {
  type: "debug";
  detectedLabel: string | null;
  confidence: number;
  scores: Record<string, number>;
  layer: string;
};
type RawMessage = { type: "raw"; fs: number; channelLabels: string[]; samples: number[][] };
type ErrorMessage = { type: "error"; message: string };
type InfoMessage = { type: "info"; message: string };
type StateMessage = ServerPlayerState & { type: "state" };
type ServerMessage = StateMessage | CommandMessage | DebugMessage | RawMessage | ErrorMessage | InfoMessage;

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
  const setStreamWarning = usePlayerStore((s) => s.setStreamWarning);
  const addDetectionEvent = usePlayerStore((s) => s.addDetectionEvent);
  const setRawChannelData = usePlayerStore((s) => s.setRawChannelData);
  const setSendRawSubscription = usePlayerStore((s) => s.setSendRawSubscription);
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    // Captures `ws` by reference (not value), so it keeps working across
    // reconnects even though `ws` itself gets reassigned to a new socket --
    // stored in playerStore so the debug panel's toggle can (un)subscribe
    // to raw channel data without the socket itself being prop-drilled.
    const sendRaw = (subscribe: boolean) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: subscribe ? "raw_subscribe" : "raw_unsubscribe" }));
      }
    };

    const connect = () => {
      if (cancelled) return;
      setWsStatus("connecting");
      const socket = new WebSocket(WS_URL);
      ws = socket;

      socket.onopen = () => {
        if (cancelled || ws !== socket) return;
        setWsStatus("connected");
        // A reconnect is a brand new server-side connection, which starts
        // with no raw subscription -- re-request it if the panel was left open.
        if (usePlayerStore.getState().debugPanelOpen) sendRaw(true);
      };

      socket.onmessage = (event) => {
        if (cancelled || ws !== socket) return;
        const msg = JSON.parse(event.data) as ServerMessage;
        if (msg.type === "state") {
          usePlayerStore.getState().setServerState(msg);
        } else if (msg.type === "debug") {
          setDetection(msg.detectedLabel, msg.confidence, msg.scores);
        } else if (msg.type === "raw") {
          setRawChannelData({ fs: msg.fs, channelLabels: msg.channelLabels, samples: msg.samples });
        } else if (msg.type === "command") {
          addDetectionEvent(msg.target, msg.layer);
          onCommandRef.current(msg);
        } else if (msg.type === "error") {
          setStreamWarning(msg.message);
        } else if (msg.type === "info") {
          setStreamWarning(null);
        }
      };

      socket.onclose = () => {
        if (cancelled || ws !== socket) return;
        setWsStatus("disconnected");
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    setSendRawSubscription(sendRaw);
    connect();

    return () => {
      cancelled = true;
      setSendRawSubscription(null);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
