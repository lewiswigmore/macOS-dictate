from __future__ import annotations

import difflib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from dictate.config import Config
from dictate.logging_setup import get_logger

if TYPE_CHECKING:
    from dictate.context import ContextProbe

log = get_logger(__name__)

_RATIO_CUTOFF = 0.9
# A "correction" requires the AX-read buffer to actually resemble what we
# typed — otherwise we'd misinterpret Terminal echo, prompts, or buffers
# from unrelated text fields as user corrections.
_RELATED_CUTOFF = 0.55
_DEFAULT_POLL_INTERVAL = 1.0


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


class LearnWatcher:
    def __init__(
        self,
        config: Config,
        history_appender: Callable[[dict], None],
        context: ContextProbe,
    ) -> None:
        self._config = config
        self._history_appender = history_appender
        self._context = context
        self._lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        # mtime-keyed cache: history file rarely changes between utterances,
        # so we avoid re-parsing on every cleanup call.
        self._cache_mtime: float | None = None
        self._cache_by_preset: dict[str, list[tuple[str, str]]] = {}

    def arm(self, raw: str, cleaned: str) -> None:
        if not self._config.get("learn.enabled", False):
            return
        # No cleanup happened (or model returned the same text) → nothing to learn from.
        if raw.strip() == cleaned.strip():
            return

        with self._lock:
            if self._stop_event is not None:
                self._stop_event.set()
            stop = threading.Event()
            self._stop_event = stop

        frontmost = self._context.frontmost()
        preset = self._context.preset_for(frontmost)
        app = frontmost.get("name")
        window_s: float = float(self._config.get("learn.watch_window_seconds", 30.0))
        poll_s: float = float(
            self._config.get("learn.poll_interval_seconds", _DEFAULT_POLL_INTERVAL)
        )

        def _watch() -> None:
            deadline = time.monotonic() + window_s
            while time.monotonic() < deadline:
                if stop.is_set():
                    return
                time.sleep(poll_s)
                if stop.is_set():
                    return
                try:
                    current = self._context.read_focused_value(frontmost=frontmost)
                except Exception:
                    continue
                if current is None:
                    continue
                cleaned_norm = cleaned.strip()
                current_norm = current.strip()
                ratio = _ratio(cleaned_norm, current_norm)
                # Skip when basically identical (no edit yet) and when
                # totally unrelated (different field or terminal buffer).
                if ratio >= _RATIO_CUTOFF or ratio < _RELATED_CUTOFF:
                    continue
                self._history_appender(
                    {
                        "type": "correction",
                        "preset": preset,
                        "raw": raw,
                        "cleaned": cleaned,
                        "correction": current,
                        "app": app,
                    }
                )
                return

        t = threading.Thread(target=_watch, daemon=True, name="learn-watcher")
        t.start()

    def recent_corrections(self, preset: str, n: int) -> list[tuple[str, str]]:
        if n <= 0:
            return []
        path = Path(self._config.history_path)
        if not path.exists():
            return []
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []

        if mtime != self._cache_mtime:
            self._rebuild_cache(path, mtime)

        bucket = self._cache_by_preset.get(preset, [])
        return bucket[-n:]

    def _rebuild_cache(self, path: Path, mtime: float) -> None:
        by_preset: dict[str, list[tuple[str, str]]] = {}
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "correction":
                        continue
                    p = entry.get("preset", "default")
                    by_preset.setdefault(p, []).append(
                        (entry.get("raw", ""), entry.get("correction", ""))
                    )
        except OSError:
            return
        self._cache_by_preset = by_preset
        self._cache_mtime = mtime
