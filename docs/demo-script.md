# Demo Script

Honest about the constraint: only one partial day of real ant-neuro
hardware access exists across the 30-day build. State this plainly during
the demo rather than implying more than was built.

1. **Problem framing (~30s).** Late-stage ALS / locked-in patients can lose
   reliable motor *and* eye-tracking control (nystagmus, severe tremor).
   SSVEP sidesteps this: flashing targets entrain the visual cortex, which
   is detectable in occipital EEG even without controlled voluntary eye
   movement — only directable visual attention is needed.

2. **Simulated segment, main body (~2-3 min).** State plainly that this
   part runs against a software-simulated EEG source
   (`simulator/mock_eeg_lsl.py`) feeding the *identical* pipeline that ran
   on real hardware — only the data source differs (see
   `backend/app/lsl_ingest.py`, the sim/real swap point). Show:
   - the debug readout (detected frequency + confidence) for judges
   - a mood tile lighting up and the curated playlist starting on real
     speakers via Spotify Connect
   - switching to the Transport layer and demonstrating play/pause/next/prev

3. **Real hardware segment (~1-2 min).** Either live, if the borrowed unit
   happens to be at the event, or — more realistically — the recorded
   video + `.xdf` replay (`simulator/scenarios/recorded_session_replay.py`)
   captured during the one hardware day, clearly labeled as such.

4. **Honesty/roadmap slide.** What's real today: an end-to-end volitional
   SSVEP command pipeline, validated once on real ant-neuro hardware. What's
   future work: passive/involuntary affective-state decoding (the
   personalized pre-paralysis model from the ALS emotion-recognition
   research), a full letter-by-letter speller, higher-refresh-rate displays
   for more/closer-spaced target frequencies, multi-session per-patient
   tuning.

5. **Have the backup video cued and ready** in case the live hardware or
   even the live simulated segment hiccups during judging.
