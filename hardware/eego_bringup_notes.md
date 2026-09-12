# ant-neuro eego Bring-up Notes

Fill this in as investigation happens, well before the one real-hardware
day — the goal is that Phase 4 (hardware bring-up) is a checklist against
this document, not a discovery session.

## To confirm before hardware day

- [ ] Which eego software version/build will be used, and is LSL streaming
      confirmed enabled in it (may be off by default or license-gated)?
- [ ] Exact LSL stream name it exports (needed for `LSL_STREAM_NAME`).
- [ ] Configured sample rate (informational only — `lsl_ingest.py` reads
      `nominal_srate()` from the stream at connect time, never hardcode it).
- [ ] Does the lent cap/montage include occipital sites (Oz, O1, O2, POz)?
      If not, which posterior site is the best fallback?
- [ ] Does the exported stream report 10-20 channel labels, or raw
      electrode indices? If raw indices, note the index numbers
      corresponding to the occipital sites for `OCCIPITAL_CHANNEL_INDICES`.
- [ ] Any dongle/license activation needed for the eego software — test
      this on the actual demo laptop ahead of time, not on hardware day.
- [ ] Confirm mains frequency at the venue (60Hz assumed for Canada).

## Bring-up day checklist (see plan doc Phase 4 for full context)

1. Launch eego acquisition software, enable/verify LSL export, note stream name.
2. Set `LSL_STREAM_NAME` in `backend/.env` to that name (only config change needed).
3. Start backend, confirm the `lsl_ingest` startup log shows the expected
   `fs`, channel labels, and resolved occipital indices.
4. Run the calibration screen against a real person; check per-target SNR.
5. Tune `WINDOW_SEC` / `CONFIDENCE_THRESHOLD` / `DWELL_SEC` live if needed.
6. Run at least one full mood-select → playback → transport pass.
7. Record video AND start an LSL recording (LabRecorder) of a full
   successful run — this becomes the Phase 5 replay asset and the demo
   backup if live hardware isn't available/reliable on judging day.

## Findings (fill in after investigation / hardware day)

- **2026-09-12, live network test (eego over LAN, 500Hz, Oz/O1/O2, PSDA):**
  10Hz and 12Hz targets (mood "Energetic" / transport "Previous", and mood
  "Sad" / transport "Back to Playlists" respectively — see
  `frontend/src/ssvep/frequencies.ts`) felt subjectively most responsive to
  the test subject, compared to 7.5Hz and 8.571Hz. A single spot-check
  (`Detector.detect_with_scores` on a live captured window) confirmed a
  clean, strong 10Hz detection (confidence 0.66, peak power ~3.1M vs next
  candidate ~830K) while directly fixating on it — so at least at 10Hz the
  detector itself is working correctly on this subject/setup; whether
  7.5/8.571Hz are inherently weaker for this subject or just weren't
  fixated as directly wasn't isolated. Worth a proper per-frequency SNR
  comparison via the calibration screen (equal fixation time each) before
  concluding anything about frequency choice — alpha-band proximity
  (~8-12Hz) and individual variability in SSVEP responsiveness are both
  plausible explanations, not necessarily a setup problem.
