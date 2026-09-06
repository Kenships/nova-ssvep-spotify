# SSVEP Spotify Player

An SSVEP (steady-state visually evoked potential) brain-computer-interface
music player for late-stage ALS patients, targeting ant-neuro's eego EEG
hardware. Flashing on-screen tiles at fixed frequencies entrain the visual
cortex; the entrained frequency is detected in occipital EEG and mapped to
mood/playlist selection and playback transport commands, sent to Spotify.

Full architecture, rationale, and the 30-day build plan (including why
each decision was made) live in the plan doc this repo was built from —
see `docs/demo-script.md` and `hardware/` for the demo- and
hardware-specific pieces.

## Repo layout

- `simulator/` — synthetic LSL EEG source. Makes the whole pipeline
  testable without real hardware in hand.
- `backend/` — FastAPI service: LSL ingest → filtering → SSVEP detection
  (PSDA or CCA) → command bus (dwell/debounce) → Spotify calls + WebSocket
  broadcast to the frontend.
- `frontend/` — React + TypeScript UI: frame-accurate flicker rendering
  (Canvas + `requestAnimationFrame`, not React state) plus the
  Spotify-style player chrome.
- `hardware/` — ant-neuro eego bring-up notes and checklist, filled in as
  investigation happens ahead of the one real-hardware day.
- `docs/` — demo script.

## Running locally (simulated EEG, no hardware needed)

**Backend:**
```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy ..\.env.example .env   # then fill in Spotify credentials if testing that part
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

**Simulator** (separate terminal):
```
backend\.venv\Scripts\python simulator\mock_eeg_lsl.py
# press 1/2/3/4 to simulate attending Calm/Happy/Energetic/Sad, 0 for idle
```

**Frontend** (separate terminal):
```
cd frontend
npm install
npm run dev
```
Then open http://localhost:5173. Or run all three at once with
`scripts/dev_up.ps1`.

## Running tests

```
cd backend
.venv\Scripts\python -m pytest tests/ -v
```

## Switching to real ant-neuro hardware

Change exactly one thing: `LSL_STREAM_NAME` in `backend/.env`, to the
stream name the eego acquisition software exports. Everything downstream
of `backend/app/lsl_ingest.py` is identical whether the data is real or
simulated. See `hardware/eego_bringup_notes.md` before the hardware
session — most of the risk is in unknowns that should be resolved ahead of
time, not discovered on the day.

## Known limitations (by design, not oversight)

- Volume is not an SSVEP-controlled target in the MVP (would need a 5th
  frequency and reintroduces a harmonic collision) — set manually.
- Mood selection is a *volitional* SSVEP choice, not passive/involuntary
  emotional-state decoding from EEG. True affective-state decoding is
  future work (see `docs/demo-script.md`).
- Spotify playback targets an already-open, logged-in Premium client via
  Spotify Connect (not an embedded Web Playback SDK) — Spotify must be
  open on some device before/while running.
