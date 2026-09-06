import { useEffect } from "react";
import { usePlayerStore } from "../state/playerStore";

const POLL_MS = 3000;

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
    return <div className="now-playing now-playing--empty">Nothing playing yet</div>;
  }

  return (
    <div className="now-playing">
      {nowPlaying.album_art_url && (
        <img src={nowPlaying.album_art_url} alt="" className="now-playing__art" />
      )}
      <div className="now-playing__meta">
        <div className="now-playing__track">{nowPlaying.track}</div>
        <div className="now-playing__artist">{nowPlaying.artist}</div>
      </div>
    </div>
  );
}
