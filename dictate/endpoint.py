"""Auto-endpoint watcher: stops a recording when the user stops talking.

Runs as a background thread during an active recording session. Feeds
incoming audio chunks through Silero VAD and fires a callback once the VAD
reports an endpoint (sustained silence after speech). This lets users speak
naturally and have the pipeline auto-finish instead of pressing Cmd+H twice.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from dictate.logging_setup import get_logger
from dictate.vad import VAD

log = get_logger(__name__)


class EndpointWatcher:
    """Background-thread VAD endpoint detector."""

    def __init__(
        self,
        *,
        recorder: Any,
        vad: VAD,
        on_endpoint: Callable[[], None],
        max_recording_ms: int = 60_000,
        is_held: Callable[[], bool] | None = None,
    ) -> None:
        self._recorder = recorder
        self._vad = vad
        self._on_endpoint = on_endpoint
        self._max_recording_ms = max(2_000, int(max_recording_ms))
        self._is_held = is_held

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._fired = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._fired = False
        self._vad.reset()
        self._thread = threading.Thread(
            target=self._run,
            name="endpoint-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            # Bounded join — the watcher loop wakes at most every 50 ms on the
            # pop_watch_chunk timeout. Joining prevents a late `_on_endpoint`
            # callback from firing after stop() returns and racing with a
            # manual hotkey-stop.
            thread.join(timeout=0.2)

    def _run(self) -> None:
        start_ts = time.monotonic()

        while not self._stop_event.is_set():
            chunk = self._recorder.pop_watch_chunk(timeout=0.05)
            if chunk is not None and len(chunk):
                try:
                    status = self._vad.process_chunk(chunk)
                except Exception:
                    log.exception("VAD process_chunk failed; stopping watcher")
                    return

                if status.get("endpoint"):
                    if self._is_held is not None:
                        try:
                            if self._is_held():
                                # User is actively holding push-to-talk; reset
                                # VAD silence accumulator and keep listening.
                                self._vad.reset()
                                continue
                        except Exception:
                            log.debug("is_held predicate raised", exc_info=True)
                    self._fire("silence")
                    return

            elapsed_ms = (time.monotonic() - start_ts) * 1000.0
            if elapsed_ms >= self._max_recording_ms:
                if self._is_held is not None:
                    try:
                        if self._is_held():
                            # Don't enforce max-duration while explicitly held
                            start_ts = time.monotonic()
                            continue
                    except Exception:
                        pass
                self._fire("max-duration")
                return

    def _fire(self, reason: str) -> None:
        if self._fired:
            return
        self._fired = True
        log.info("auto-endpoint fired (%s)", reason)
        try:
            self._on_endpoint()
        except Exception:
            log.exception("on_endpoint callback raised")
