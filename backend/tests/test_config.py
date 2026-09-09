from app.config import Settings, _env_float_list, settings


def test_env_float_list_parses_comma_separated_values(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT_LIST", "1.0,2.5,3")
    assert _env_float_list("SOME_FLOAT_LIST", [0.0]) == [1.0, 2.5, 3.0]


def test_env_float_list_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLOAT_LIST", raising=False)
    assert _env_float_list("SOME_FLOAT_LIST", [9.0, 8.0]) == [9.0, 8.0]


def test_env_float_list_falls_back_to_default_when_empty(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT_LIST", "")
    assert _env_float_list("SOME_FLOAT_LIST", [1.0]) == [1.0]


def test_mood_and_transport_frequencies_are_collision_free():
    # Regression guard for the documented invariant (see config.py): no
    # candidate frequency may equal another candidate's 2nd harmonic, or the
    # PSDA/CCA fundamental+harmonic scoring could confuse two targets.
    for freqs in (settings.mood_frequencies, settings.transport_frequencies):
        values = list(freqs.values())
        for f in values:
            assert not any(abs(f - 2 * other) < 1e-6 for other in values if other != f)


def test_load_mood_playlists_reads_the_config_file():
    data = settings.load_mood_playlists()
    assert "moods" in data
    assert len(data["moods"]) == 4


def test_settings_is_a_plain_dataclass_instance():
    # Constructing a second instance must not blow up or require env vars --
    # confirms defaults are self-contained rather than depending on some
    # runtime side effect only performed for the module-level singleton.
    other = Settings()
    assert other.bandpass_low_hz == settings.bandpass_low_hz
    assert other.mood_frequencies == settings.mood_frequencies
