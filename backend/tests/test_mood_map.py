from app.spotify.mood_map import frequency_map, load_moods, playlist_uri_for


def test_load_moods_returns_the_four_configured_moods():
    moods = load_moods()
    ids = {m["id"] for m in moods}
    assert ids == {"calm", "happy", "energetic", "sad"}
    assert all("freqHz" in m and "spotify_playlist_uri" in m for m in moods)


def test_frequency_map_matches_backend_candidate_set():
    moods = load_moods()
    freqs = frequency_map(moods)
    assert freqs["calm"] == 15.0
    assert freqs["energetic"] == 18.0
    assert freqs["sad"] == 19.5
    assert freqs["happy"] == 16.5


def test_playlist_uri_for_known_and_unknown_mood():
    moods = load_moods()
    assert playlist_uri_for(moods, "calm") is not None
    assert playlist_uri_for(moods, "not-a-mood") is None
