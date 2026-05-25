"""Tiny audio cues for recording start / end.

Plays one of macOS's built-in system sounds via ``NSSound``. These are short
(~100 ms), free, don't ship any audio assets, and play in a fire-and-forget
fashion off the main thread — so they never block the hotkey path.

Falls back to a silent no-op if AppKit is unavailable (test env) or the named
sound can't be loaded (very old macOS / sound file removed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .logging_setup import get_logger

if TYPE_CHECKING:
    from .config import Config

log = get_logger(__name__)

try:
    from AppKit import NSSound

    _AVAILABLE = True
except ImportError:  # pragma: no cover — only hit in test envs without pyobjc
    NSSound = None  # type: ignore[assignment,misc]
    _AVAILABLE = False


# Catalog of cue keys → macOS system sound names. Add new cues by extending
# this dict rather than hardcoding sound names at call sites.
#
# Defaults chosen for: short (<150 ms), distinct rising/falling pitch so users
# can tell start from end without looking, and quiet enough to be unobtrusive.
SOUNDS: dict[str, str] = {
    "start": "Tink",  # rising-pitch tap — "armed"
    "end": "Pop",  # short low pop — "released"
    "cancel": "Funk",  # neutral cancel
}


class AudioCues:
    """Plays start/end cues; honours ``ui.audio_cues`` setting."""

    def __init__(self, config: Config) -> None:
        self._enabled: bool = bool(config.get("ui.audio_cues", True))
        # Pre-load NSSound instances so the first play has no disk-IO latency.
        self._sounds: dict[str, object] = {}
        if _AVAILABLE and self._enabled:
            self._preload()

    def _preload(self) -> None:
        for key, name in SOUNDS.items():
            try:
                snd = NSSound.soundNamed_(name)
                if snd is not None:
                    self._sounds[key] = snd
                else:
                    log.debug("system sound not found: %s", name)
            except Exception:  # noqa: BLE001
                log.debug("failed to preload sound %s", name, exc_info=True)

    def play(self, key: str) -> bool:
        """Fire a cue. Returns True if a sound was actually started."""
        if not self._enabled:
            return False
        snd = self._sounds.get(key)
        if snd is None:
            return False
        try:
            # NSSound.play is non-blocking; if a previous instance is still
            # playing we stop+rewind so rapid start/stop cycles still fire.
            snd.stop()
            return bool(snd.play())
        except Exception:  # noqa: BLE001
            log.debug("failed to play cue %s", key, exc_info=True)
            return False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        if on and not self._sounds and _AVAILABLE:
            self._preload()
