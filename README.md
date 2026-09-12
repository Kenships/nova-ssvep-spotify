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
- `scripts/` — `run.bat` / `dev_up.ps1` (start everything) and
  `dev_down.ps1` (stop everything).

## Running locally (simulated EEG, no hardware needed)

**One command** (after the one-time backend venv setup below): double-click
`scripts/run.bat`, or from a terminal:
```
powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
```
Starts the simulator, backend, and frontend each in their own window,
clears any stray processes left over from a previous run first, and opens
http://localhost:5173 once the frontend is up. Pass `-DetectorBackend cca`
to use the CCA detector instead of PSDA, or `-SimFreq 10.0` to have the
simulator attend a fixed frequency from launch. Stop everything with:
```
powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1
```

**One-time backend setup** (dev_up.ps1 needs this to exist first):
```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy ..\.env.example .env   # then fill in Spotify credentials if testing that part
```
(`dev_up.ps1` also runs `npm install` for the frontend automatically on
first launch if `frontend/node_modules` is missing.)

**Running the three pieces by hand instead**, e.g. to watch one's logs in
its own foreground terminal:
```
# backend
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# simulator (separate terminal)
backend\.venv\Scripts\python simulator\mock_eeg_lsl.py
# press 1/2/3/4 to simulate attending Calm/Happy/Energetic/Sad, 0 for idle

# frontend (separate terminal)
cd frontend
npm run dev
```

## Running tests

```
cd backend
.venv\Scripts\python -m pytest tests/ -v
```

`backend/app` is held to 100% line coverage (enforced via `backend/pytest.ini`).
The simulator and `scripts/smoke_test_ws_client.py` have their own suite,
covered the same way, run from the repo root instead (uses the same venv):
```
backend\.venv\Scripts\python -m pytest
```

Frontend state/reconnection regressions and the production build:
```
cd frontend
npm test
npm run build
```

Calibration pauses playback commands on the backend for all connected
clients. Reloading restores that paused state; use **Exit calibration** or
**Continue to Player** to resume. Automatic detection waits for the
calibration stimulus to leave the analysis window before accepting inputs.
Choose **Start signal check** to measure each target; the check reports SNR
and does not train the detector or save calibration settings. Each target
waits for a fresh analysis window before readings are accepted. Missing or
failed readings are shown as unavailable, and **Run again** repeats the check.
If the EEG source is absent at startup, the backend retries discovery while
keeping the API available. Source switches wait for the old reader to stop.

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
