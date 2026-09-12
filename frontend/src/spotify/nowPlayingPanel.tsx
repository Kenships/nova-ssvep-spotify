import { useEffect } from "react";
import { usePlayerStore } from "../state/playerStore";

const POLL_MS = 3000;

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

export function NowPlayingPanel() {
  const nowPlaying = usePlayerStore((s) => s.nowPlaying);
  const setNowPlaying = usePlayerStore((s) => s.setNowPlaying);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/now-playing");
        const data = await res.json();
        if (!cancelled) setNowPlaying(data?.track ? data : null);
      } catch {
        if (!cancelled) setNowPlaying(null);
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setNowPlaying]);

  if (!nowPlaying) {
    return (
      <div className="now-playing now-playing--empty">
        <div className="now-playing__art now-playing__art--placeholder" />
        <div className="now-playing__meta">
          <div className="now-playing__track">Nothing playing</div>
          <div className="now-playing__artist">Pick a mood to start</div>
        </div>
      </div>
    );
  }

  const progressPct = nowPlaying.duration_ms
    ? Math.min(100, (nowPlaying.progress_ms / nowPlaying.duration_ms) * 100)
    : 0;

  return (
    <div className="now-playing">
      {nowPlaying.album_art_url ? (
        <img src={nowPlaying.album_art_url} alt="" className="now-playing__art" />
      ) : (
        <div className="now-playing__art now-playing__art--placeholder" />
      )}
      <div className="now-playing__meta">
        <div className="now-playing__track">{nowPlaying.track}</div>
        <div className="now-playing__artist">{nowPlaying.artist}</div>
        <div className="now-playing__progress">
          <div className="now-playing__progress-bar">
            <div className="now-playing__progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="now-playing__time">
            {formatTime(nowPlaying.progress_ms)} / {formatTime(nowPlaying.duration_ms)}
          </div>
        </div>
      </div>
      <div className={`now-playing__status now-playing__status--${nowPlaying.is_playing ? "playing" : "paused"}`}>
        {nowPlaying.is_playing ? "⏸" : "▶"}
      </div>
    </div>
  );
}
