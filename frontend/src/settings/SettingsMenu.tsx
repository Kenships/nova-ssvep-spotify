import { useEffect, useRef, useState } from "react";
import { FLICKER_MODE_OPTIONS } from "../ssvep/flickerModes";
import { usePlayerStore } from "../state/playerStore";

export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const flickerMode = usePlayerStore((s) => s.flickerMode);
  const setFlickerMode = usePlayerStore((s) => s.setFlickerMode);
  const containerRef = useRef<HTMLDivElement | null>(null);

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
          <div className="settings-menu__footnote">Tiles are always clickable, in any mode.</div>
        </div>
      )}
    </div>
  );
}
