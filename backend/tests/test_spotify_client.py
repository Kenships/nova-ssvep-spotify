"""Tests SpotifyClient against fake spotipy objects injected directly into
its `_client`/`_auth_manager` slots -- never a real spotipy.Spotify /
SpotifyOAuth instance, so these tests can never make a real network call or
control a real, currently-playing Spotify device.
"""
from app.config import settings
from app.spotify.spotify_client import SpotifyClient


class FakeAuthManager:
    def __init__(self, cached_token=None):
        self._cached_token = cached_token
        self.completed_codes = []

    def get_cached_token(self):
        return self._cached_token

    def validate_token(self, token_info):
        return token_info

    def get_authorize_url(self):
        return "https://accounts.spotify.com/authorize?fake=1"

    def get_access_token(self, code, as_dict=False, check_cache=False):
        self.completed_codes.append(code)


class FakeSpotify:
    def __init__(self, devices=None, playback=None):
        self._devices = devices if devices is not None else []
        self._playback = playback
        self.calls: list[tuple[str, dict]] = []

    def devices(self):
        return {"devices": self._devices}

    def start_playback(self, **kwargs):
        self.calls.append(("start_playback", kwargs))

    def pause_playback(self):
        self.calls.append(("pause_playback", {}))

    def current_playback(self):
        return self._playback

    def next_track(self):
        self.calls.append(("next_track", {}))

    def previous_track(self):
        self.calls.append(("previous_track", {}))

    def volume(self, percent):
        self.calls.append(("volume", percent))


def _client_with(devices=None, playback=None) -> tuple[SpotifyClient, FakeSpotify]:
    sc = SpotifyClient()
    fake = FakeSpotify(devices=devices, playback=playback)
    sc._client = fake
    return sc, fake


def test_is_authenticated_false_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "spotify_client_id", "")
    monkeypatch.setattr(settings, "spotify_client_secret", "")
    sc = SpotifyClient()
    assert sc.is_authenticated() is False


def test_is_authenticated_true_with_valid_cached_token(monkeypatch):
    monkeypatch.setattr(settings, "spotify_client_id", "id")
    monkeypatch.setattr(settings, "spotify_client_secret", "secret")
    sc = SpotifyClient()
    sc._auth_manager = FakeAuthManager(cached_token={"access_token": "x"})
    assert sc.is_authenticated() is True


def test_is_authenticated_false_with_no_cached_token(monkeypatch):
    monkeypatch.setattr(settings, "spotify_client_id", "id")
    monkeypatch.setattr(settings, "spotify_client_secret", "secret")
    sc = SpotifyClient()
    sc._auth_manager = FakeAuthManager(cached_token=None)
    assert sc.is_authenticated() is False


def test_get_authorize_url_and_complete_authorization():
    sc = SpotifyClient()
    fake_auth = FakeAuthManager()
    sc._auth_manager = fake_auth
    assert sc.get_authorize_url() == "https://accounts.spotify.com/authorize?fake=1"
    sc.complete_authorization("auth-code-123")
    assert fake_auth.completed_codes == ["auth-code-123"]


def test_resolve_device_id_returns_none_when_no_devices():
    sc, _fake = _client_with(devices=[])
    assert sc._resolve_device_id() is None


def test_resolve_device_id_prefers_configured_name(monkeypatch):
    monkeypatch.setattr(settings, "spotify_device_name", "Kitchen Speaker")
    sc, _fake = _client_with(devices=[{"id": "d1", "name": "Phone"}, {"id": "d2", "name": "Kitchen Speaker"}])
    assert sc._resolve_device_id() == "d2"


def test_resolve_device_id_falls_back_to_first_when_configured_name_missing(monkeypatch):
    monkeypatch.setattr(settings, "spotify_device_name", "Nonexistent")
    sc, _fake = _client_with(devices=[{"id": "d1", "name": "Phone"}])
    assert sc._resolve_device_id() == "d1"


def test_resolve_device_id_returns_first_when_no_name_configured(monkeypatch):
    monkeypatch.setattr(settings, "spotify_device_name", "")
    sc, _fake = _client_with(devices=[{"id": "d1", "name": "Phone"}])
    assert sc._resolve_device_id() == "d1"


def test_play_playlist_uses_context_uri_for_a_playlist():
    sc, fake = _client_with(devices=[{"id": "d1", "name": "Phone"}])
    sc.play_playlist("spotify:playlist:abc123")
    assert fake.calls == [("start_playback", {"device_id": "d1", "context_uri": "spotify:playlist:abc123"})]


def test_play_playlist_uses_uris_list_for_a_track():
    sc, fake = _client_with(devices=[{"id": "d1", "name": "Phone"}])
    sc.play_playlist("spotify:track:xyz789")
    assert fake.calls == [("start_playback", {"device_id": "d1", "uris": ["spotify:track:xyz789"]})]


def test_toggle_play_pause_pauses_when_playing():
    sc, fake = _client_with(playback={"is_playing": True})
    sc.toggle_play_pause()
    assert fake.calls == [("pause_playback", {})]


def test_toggle_play_pause_resumes_when_not_playing():
    sc, fake = _client_with(playback={"is_playing": False})
    sc.toggle_play_pause()
    assert fake.calls == [("start_playback", {})]


def test_toggle_play_pause_resumes_when_nothing_playing():
    sc, fake = _client_with(playback=None)
    sc.toggle_play_pause()
    assert fake.calls == [("start_playback", {})]


def test_next_and_previous_track():
    sc, fake = _client_with()
    sc.next_track()
    sc.previous_track()
    assert fake.calls == [("next_track", {}), ("previous_track", {})]


def test_set_volume_clamps_to_0_100():
    sc, fake = _client_with()
    sc.set_volume(150)
    sc.set_volume(-10)
    sc.set_volume(42)
    assert fake.calls == [("volume", 100), ("volume", 0), ("volume", 42)]


def test_now_playing_returns_none_when_nothing_playing():
    sc, _fake = _client_with(playback=None)
    assert sc.now_playing() is None


def test_now_playing_returns_none_when_no_item():
    sc, _fake = _client_with(playback={"is_playing": False})
    assert sc.now_playing() is None


def test_now_playing_formats_full_playback_state():
    sc, _fake = _client_with(
        playback={
            "is_playing": True,
            "progress_ms": 1000,
            "item": {
                "name": "Song Title",
                "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                "album": {"images": [{"url": "http://example.com/art.jpg"}]},
                "duration_ms": 200000,
            },
        }
    )
    result = sc.now_playing()
    assert result == {
        "track": "Song Title",
        "artist": "Artist A, Artist B",
        "album_art_url": "http://example.com/art.jpg",
        "is_playing": True,
        "progress_ms": 1000,
        "duration_ms": 200000,
    }


def test_auth_manager_is_lazily_constructed_and_cached():
    # Real SpotifyOAuth() construction (no network I/O happens at
    # construction time -- only real endpoint calls would need credentials).
    sc = SpotifyClient()
    first = sc.auth_manager
    second = sc.auth_manager
    assert first is second


def test_client_is_lazily_constructed_and_cached():
    sc = SpotifyClient()
    sc._auth_manager = FakeAuthManager()
    first = sc.client
    second = sc.client
    assert first is second


def test_now_playing_handles_missing_album_art():
    sc, _fake = _client_with(
        playback={
            "is_playing": True,
            "item": {"name": "Song", "artists": [], "album": {}, "duration_ms": 100},
        }
    )
    result = sc.now_playing()
    assert result["album_art_url"] is None
    assert result["artist"] == ""
