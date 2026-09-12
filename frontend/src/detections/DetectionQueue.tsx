import { labelForTileId } from "../ssvep/frequencies";
import { usePlayerStore } from "../state/playerStore";

function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
}

/** Shows the most recently *registered* inputs (fired commands that passed
 * dwell/debounce) -- not every raw per-window detector tick, which is far
 * too noisy to read as a list. See app__debug for the live raw tick. */
export function DetectionQueue() {
  const history = usePlayerStore((s) => s.detectionHistory);

  return (
    <div className="detection-queue">
      <span className="detection-queue__label">Recent detections</span>
      {history.length === 0 ? (
        <span className="detection-queue__empty">none yet</span>
      ) : (
        <ol className="detection-queue__list">
          {history.map((event, i) => (
            <li
              key={event.timestamp}
              className={
                i === 0 ? "detection-queue__item detection-queue__item--latest" : "detection-queue__item"
              }
            >
              <span className="detection-queue__item-label">{labelForTileId(event.label)}</span>
              <span className="detection-queue__item-time">{formatClock(event.timestamp)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
