# Launching the ant-neuro eego LSL Stream

Placeholder — fill in with the exact steps once the eego software is in
hand, so hardware day is a checklist, not a discovery session. Expected
shape based on ant-neuro's documented tooling (confirm against the actual
software version used):

1. Install/launch the eego acquisition software (`eego-vendor` or
   equivalent) with the amplifier connected via USB.
2. Apply the correct cap/montage file so channels report 10-20 labels
   rather than raw electrode indices (if a montage file is available for
   the lent cap).
3. Enable LSL streaming output in the software's settings (check under
   a "streaming" / "network" / "LSL" panel — exact location varies by
   version; note it here once found).
4. Confirm the stream is visible to other LSL tools, e.g. run
   `python -c "from pylsl import resolve_streams; print(resolve_streams())"`
   from the backend venv and confirm an EEG-type stream appears.
5. Note the exact stream `name` field — that's what goes into
   `LSL_STREAM_NAME` in `backend/.env`.

## Known risks (see eego_bringup_notes.md for the full list)

- LSL export may be off by default or require a specific software
  version/license.
- Sample rate and channel naming are configurable — never hardcoded
  downstream; `lsl_ingest.py` reads both from the stream itself.
