"""Maps a detected frequency label to a logical command for the currently
active layer, with dwell/debounce and refractory gating.

This debounce logic matters at least as much as raw classifier accuracy
for a good demo: a single noisy detection should never fire a command, and
a fired command should not immediately re-fire on the next window.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Layer(str, Enum):
    MOOD = "mood"
    TRANSPORT = "transport"


@dataclass
class CommandBus:
    dwell_sec: float
    refractory_sec: float
    layer: Layer = Layer.MOOD

    _pending_label: str | None = field(default=None, init=False)
    _pending_since: float | None = field(default=None, init=False)
    _refractory_until: float = field(default=0.0, init=False)

    def reset_dwell(self) -> None:
        self._pending_label = None
        self._pending_since = None

    def enter_refractory(self, now: float | None = None) -> None:
        """Reset dwell and block the next `refractory_sec` worth of feed()
        calls from firing. Used both by switch_layer (below) and by a
        manually-triggered command (see main.py's /api/manual-command) so a
        manual click can't be immediately followed by a stale/coincidental
        automatic re-fire of the same target.
        """
        now = now if now is not None else time.monotonic()
        self.reset_dwell()
        self._refractory_until = now + self.refractory_sec

    def switch_layer(self, layer: Layer, now: float | None = None) -> None:
        self.layer = layer
        self.enter_refractory(now)

    def feed(self, label: str | None, now: float | None = None) -> str | None:
        """Feed one detector output (label or None). Returns a fired command
        label, or None if nothing should fire yet.
        """
        now = now if now is not None else time.monotonic()

        if now < self._refractory_until:
            return None

        if label is None:
            self.reset_dwell()
            return None

        if label != self._pending_label:
            self._pending_label = label
            self._pending_since = now
            return None

        assert self._pending_since is not None
        if now - self._pending_since < self.dwell_sec:
            return None

        # Fired: enter refractory, clear dwell state.
        self.reset_dwell()
        self._refractory_until = now + self.refractory_sec
        return label
