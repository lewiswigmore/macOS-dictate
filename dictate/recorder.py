from __future__ import annotations

import queue
import threading
from typing import Any

import numpy as np

from .logging_setup import get_logger

log = get_logger(__name__)

try:
    from AppKit import NSWorkspace, NSWorkspaceDidWakeNotification
    from AVFoundation import AVAudioEngine
    from Foundation import NSNotificationCenter

    _AVFOUNDATION_AVAILABLE = True
except ImportError:
    AVAudioEngine = None  # type: ignore[assignment,misc]
    NSNotificationCenter = None  # type: ignore[assignment,misc]
    NSWorkspace = None  # type: ignore[assignment,misc]
    NSWorkspaceDidWakeNotification = "NSWorkspaceDidWakeNotification"  # type: ignore[assignment]
    _AVFOUNDATION_AVAILABLE = False

_TARGET_SAMPLE_RATE: int = 16000
_BUFFER_FRAMES: int = 2048  # 128ms @ 16kHz — fewer wake-ups than 1024 with no UX impact
_CONFIG_CHANGE_NOTIFICATION = "AVAudioEngineConfigurationChangeNotification"


def _resample(data: np.ndarray, from_rate: float, to_rate: float) -> np.ndarray:
    """Linear-interpolation resample; handles mono float32 arrays."""
    if abs(from_rate - to_rate) < 1.0:
        return data
    new_len = max(1, round(len(data) * to_rate / from_rate))
    x_old = np.linspace(0.0, 1.0, len(data), dtype=np.float64)
    x_new = np.linspace(0.0, 1.0, new_len, dtype=np.float64)
    return np.interp(x_new, x_old, data).astype(np.float32)


class MicRecorder:
    """
    Captures microphone audio via AVAudioEngine.

    Produces 16 kHz mono float32 buffers and exposes them through a
    thread-safe queue.  Handles device hot-plug (AirPods etc.) by
    subscribing to AVAudioEngineConfigurationChangeNotification.
    """

    def __init__(self, sample_rate: int = _TARGET_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        # Secondary tap: lets a background watcher (e.g. auto-endpoint VAD)
        # consume chunks without stealing samples from the main pipeline.
        self._watch_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._engine: Any = None
        self._config_observer: Any = None
        self._wake_observer: Any = None
        self._is_running: bool = False
        self._vu_level: float = 0.0
        self._native_rate: float = float(sample_rate)
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def vu_level(self) -> float:
        return self._vu_level

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _AVFOUNDATION_AVAILABLE:
            raise RuntimeError("AVFoundation (pyobjc) not available; cannot start MicRecorder.")
        with self._lock:
            if self._is_running:
                return
            self._build_engine()
            self._is_running = True

    def stop(self) -> np.ndarray:
        with self._lock:
            if not self._is_running:
                return np.array([], dtype=np.float32)
            self._teardown_engine()
            self._is_running = False

        self._drain_watch_queue()
        return self._drain_queue()

    def cancel(self) -> None:
        with self._lock:
            if not self._is_running:
                return
            self._teardown_engine()
            self._is_running = False

        # Drop all buffered audio
        self._drop_pending_buffers()

    def pop_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Return next audio chunk for the streaming VAD/ASR consumer."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def pop_watch_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Return next audio chunk for the endpoint-detection watcher.

        Independent of pop_chunk — chunks are tee'd to both queues so the
        watcher can run VAD on live audio without consuming samples the main
        pipeline will need.
        """
        try:
            return self._watch_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _drain_watch_queue(self) -> None:
        while not self._watch_queue.empty():
            try:
                self._watch_queue.get_nowait()
            except queue.Empty:
                break

    # ------------------------------------------------------------------
    # Engine lifecycle
    # ------------------------------------------------------------------

    def _build_engine(self) -> None:
        """Build and start AVAudioEngine; installs input tap.

        Important: on input nodes, the tap format MUST match the node's own
        output (input) format — Core Audio refuses any other format with
        ``Failed to create tap due to format mismatch``. We therefore install
        the tap at the native sample rate and resample to 16 kHz in the
        callback (see :func:`_resample`).
        """
        engine = AVAudioEngine.alloc().init()

        native_fmt = engine.inputNode().inputFormatForBus_(0)
        self._native_rate = float(native_fmt.sampleRate())

        engine.inputNode().installTapOnBus_bufferSize_format_block_(
            0,
            _BUFFER_FRAMES,
            native_fmt,
            self._tap_callback,
        )

        error_ptr = None
        ok = engine.startAndReturnError_(error_ptr)
        if not ok:
            raise RuntimeError("AVAudioEngine failed to start")

        self._engine = engine
        self._subscribe_notifications()

    def _teardown_engine(self) -> None:
        self._unsubscribe_notifications()
        if self._engine is None:
            return
        try:
            self._engine.inputNode().removeTapOnBus_(0)
        except Exception:
            pass
        try:
            self._engine.stop()
        except Exception:
            pass
        self._engine = None

    def _drop_pending_buffers(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._drain_watch_queue()

    def _reset_engine(self, reason: str, *, drop_buffers: bool) -> None:
        with self._lock:
            if not self._is_running and self._engine is None:
                return
            was_running = self._is_running
            try:
                self._teardown_engine()
                if drop_buffers:
                    self._drop_pending_buffers()
                if was_running:
                    self._build_engine()
                log.info("AVAudioEngine reset after %s", reason)
            except Exception:
                log.exception("Failed to reset AVAudioEngine after %s", reason)

    def _rebuild_engine(self) -> None:
        """Called on configuration change notification (device hot-plug)."""
        self._reset_engine("audio route change", drop_buffers=False)

    def _reset_engine_after_wake(self) -> None:
        self._reset_engine("system wake", drop_buffers=True)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _subscribe_notifications(self) -> None:
        center = NSNotificationCenter.defaultCenter()
        self._config_observer = center.addObserverForName_object_queue_usingBlock_(
            _CONFIG_CHANGE_NOTIFICATION,
            None,
            None,
            self._handle_config_change_notification,
        )
        if NSWorkspace is not None:
            workspace_center = NSWorkspace.sharedWorkspace().notificationCenter()
            self._wake_observer = workspace_center.addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidWakeNotification,
                None,
                None,
                self._handle_wake_notification,
            )

    def _unsubscribe_notifications(self) -> None:
        if self._config_observer is not None:
            NSNotificationCenter.defaultCenter().removeObserver_(self._config_observer)
            self._config_observer = None
        if self._wake_observer is not None and NSWorkspace is not None:
            NSWorkspace.sharedWorkspace().notificationCenter().removeObserver_(self._wake_observer)
            self._wake_observer = None

    def _handle_config_change_notification(self, notification: Any) -> None:
        try:
            self._rebuild_engine()
        except Exception:
            log.exception("Error handling AVAudioEngine config change")

    def _handle_wake_notification(self, notification: Any) -> None:
        try:
            self._reset_engine_after_wake()
        except Exception:
            log.exception("Error handling NSWorkspace wake notification")

    # ------------------------------------------------------------------
    # Tap callback
    # ------------------------------------------------------------------

    def _tap_callback(self, buffer: Any, when: Any) -> None:
        """AVAudioEngine tap block; called on an audio thread."""
        try:
            frames = int(buffer.frameLength())
            if frames == 0:
                return

            # ``floatChannelData()`` returns a tuple of ``objc.varlist``
            # — one per channel. ``varlist.as_tuple(n)`` materializes the
            # first ``n`` Float32 samples into a Python tuple, which numpy
            # can wrap zero-copy-ish into an ndarray.
            channel0 = buffer.floatChannelData()[0]
            arr = np.fromiter(channel0.as_tuple(frames), dtype=np.float32, count=frames)

            tap_rate = float(buffer.format().sampleRate())
            if abs(tap_rate - self._sample_rate) > 1.0:
                arr = _resample(arr, tap_rate, float(self._sample_rate))

            self._vu_level = float(np.max(np.abs(arr))) if len(arr) else 0.0
            self._queue.put_nowait(arr)
            try:
                self._watch_queue.put_nowait(arr)
            except queue.Full:
                pass
        except Exception:
            log.exception("Error in AVAudioEngine tap callback")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _drain_queue(self) -> np.ndarray:
        chunks: list[np.ndarray] = []
        while not self._queue.empty():
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return (
            np.concatenate(chunks, dtype=np.float32) if chunks else np.array([], dtype=np.float32)
        )
