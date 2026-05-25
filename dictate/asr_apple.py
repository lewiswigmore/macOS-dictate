"""Apple SFSpeechRecognizer backend for dictate.

Sync wrapper: takes an already-recorded float32 mono buffer and returns the
final on-device transcript. No live partials yet — matches the existing
``ASR.transcribe_final`` contract so it can drop into the dispatcher.

Notes:
* Requires user authorization (handled at app start via
  :func:`request_authorization_blocking`).
* Forces ``requiresOnDeviceRecognition = True`` — no network, no Apple cloud.
* Does NOT support custom vocabulary / ``initial_prompt`` (Apple has no
  direct equivalent). The brand-vocab boost we get with faster-whisper is
  lost when this backend is active — surface this in the UI.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

# SFSpeechRecognizerAuthorizationStatus values (mirrored to avoid the import
# in non-darwin environments / test fixtures).
AUTH_NOT_DETERMINED = 0
AUTH_DENIED = 1
AUTH_RESTRICTED = 2
AUTH_AUTHORIZED = 3

# SFSpeechRecognitionTaskHintDictation
_TASK_HINT_DICTATION = 3
# AVAudioPCMFormatFloat32
_AV_AUDIO_FORMAT_FLOAT32 = 1


@dataclass(frozen=True)
class _SpeechModules:
    recognizer_cls: Any
    request_cls: Any
    audio_format_cls: Any
    pcm_buffer_cls: Any


_SPEECH: _SpeechModules | None = None
_SPEECH_IMPORT_FAILED = False


def _speech() -> _SpeechModules | None:
    """Lazy, cached import of the Speech + AVFoundation symbols we need."""
    global _SPEECH, _SPEECH_IMPORT_FAILED
    if _SPEECH is not None:
        return _SPEECH
    if _SPEECH_IMPORT_FAILED:
        return None
    try:
        from AVFoundation import AVAudioFormat, AVAudioPCMBuffer  # type: ignore[import]
        from Speech import (  # type: ignore[import]
            SFSpeechAudioBufferRecognitionRequest,
            SFSpeechRecognizer,
        )

        _SPEECH = _SpeechModules(
            recognizer_cls=SFSpeechRecognizer,
            request_cls=SFSpeechAudioBufferRecognitionRequest,
            audio_format_cls=AVAudioFormat,
            pcm_buffer_cls=AVAudioPCMBuffer,
        )
        return _SPEECH
    except Exception:
        log.debug("Speech / AVFoundation import failed", exc_info=True)
        _SPEECH_IMPORT_FAILED = True
        return None


def speech_available() -> bool:
    return _speech() is not None


def current_auth_status() -> int:
    mod = _speech()
    if mod is None:
        return AUTH_DENIED
    try:
        return int(mod.recognizer_cls.authorizationStatus())
    except Exception:
        return AUTH_DENIED


def request_authorization_blocking(timeout: float = 30.0) -> int:
    """Request Speech permission and wait for the user to respond.

    Two modes:
      * If the caller is on the main thread (no live NSApp run loop), we pump
        the current run loop in short slices so the system prompt can surface
        and its main-queue callback can fire.
      * Otherwise (e.g. called from a daemon thread inside the live menu-bar
        app, where rumps already drives NSApp's run loop) we just wait on
        the event — the run loop will dispatch the handler for us.
    """
    mod = _speech()
    if mod is None:
        return AUTH_DENIED

    done = threading.Event()
    result: dict[str, int] = {}

    def handler(status):  # type: ignore[no-untyped-def]
        try:
            result["status"] = int(status)
        finally:
            done.set()

    mod.recognizer_cls.requestAuthorization_(handler)

    on_main = threading.current_thread() is threading.main_thread()
    if on_main:
        try:
            from Foundation import NSDate, NSRunLoop  # type: ignore[import]

            deadline = time.monotonic() + timeout
            while not done.is_set() and time.monotonic() < deadline:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        except Exception:
            log.debug("Foundation import / run loop pump failed", exc_info=True)
            done.wait(timeout=timeout)
    else:
        done.wait(timeout=timeout)

    return result.get("status", current_auth_status())


class AppleASR:
    """Drop-in counterpart for the relevant parts of :class:`ASR`.

    Only ``load`` / ``transcribe_final`` / ``meets_confidence`` are
    implemented — ``transcribe_partial`` is unsupported in v1.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._language: str | None = config.get("asr.language", "en") or None
        self._sample_rate: int = int(config.get("audio.sample_rate", 16000))
        self._timeout_s: float = float(config.get("asr.apple.timeout_s", 15.0))
        self._lock = threading.Lock()
        self._recognizer: Any | None = None

    def load(self) -> None:
        """Instantiate the SFSpeechRecognizer. Idempotent + thread-safe."""
        with self._lock:
            if self._recognizer is not None:
                return
            mod = _speech()
            if mod is None:
                raise RuntimeError("Speech framework not available on this system")

            status = int(mod.recognizer_cls.authorizationStatus())
            if status != AUTH_AUTHORIZED:
                raise PermissionError(
                    f"Speech recognition not authorized (status={status}). "
                    "Open System Settings → Privacy & Security → Speech Recognition "
                    "and enable access for this app."
                )

            locale_id = self._language or "en-US"
            if "-" not in locale_id:
                locale_id = "en-US"
            try:
                from Foundation import NSLocale  # type: ignore[import]

                locale = NSLocale.alloc().initWithLocaleIdentifier_(locale_id)
                recognizer = mod.recognizer_cls.alloc().initWithLocale_(locale)
            except Exception:
                recognizer = mod.recognizer_cls.alloc().init()

            if recognizer is None or not recognizer.isAvailable():
                raise RuntimeError("SFSpeechRecognizer unavailable for locale " + locale_id)
            if hasattr(recognizer, "setDefaultTaskHint_"):
                try:
                    recognizer.setDefaultTaskHint_(_TASK_HINT_DICTATION)
                except Exception:
                    pass
            self._recognizer = recognizer
            log.info("apple SFSpeechRecognizer loaded (locale=%s)", locale_id)

    # ------------------------------------------------------------------ helpers
    def _make_buffer(self, samples: np.ndarray) -> Any:
        mod = _speech()
        assert mod is not None
        fmt = mod.audio_format_cls.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
            _AV_AUDIO_FORMAT_FLOAT32,
            float(self._sample_rate),
            1,
            False,
        )
        n = int(len(samples))
        buf = mod.pcm_buffer_cls.alloc().initWithPCMFormat_frameCapacity_(fmt, n)
        if buf is None:
            raise RuntimeError("AVAudioPCMBuffer alloc failed")
        buf.setFrameLength_(n)
        chan = buf.floatChannelData()
        if chan is None:
            raise RuntimeError("AVAudioPCMBuffer floatChannelData is None")
        # PyObjC exposes the underlying C float* as a mutable slice. Slot in
        # our float32 samples directly to avoid a copy.
        chan[0][:n] = samples.astype(np.float32, copy=False)
        return buf

    @staticmethod
    def _segments_from_transcription(transcription: Any) -> tuple[list[dict[str, Any]], float]:
        segments: list[dict[str, Any]] = []
        confs: list[float] = []
        try:
            for seg in transcription.segments():
                try:
                    conf = float(seg.confidence())
                except Exception:
                    conf = 0.0
                ts = float(seg.timestamp())
                segments.append(
                    {
                        "start": ts,
                        "end": ts + float(seg.duration()),
                        "text": str(seg.substring()),
                        "avg_logprob": conf,
                    }
                )
                confs.append(conf)
        except Exception:
            log.debug("segment iteration failed", exc_info=True)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return segments, avg_conf

    # ------------------------------------------------------------------ public
    def transcribe_final(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,  # noqa: ARG002 — Apple ignores
        language: str | None = None,  # noqa: ARG002 — set at load time
    ) -> dict[str, Any]:
        # Ensure a recognizer is available, then capture it locally so a
        # concurrent reload()/load() that nils self._recognizer can't make
        # us crash mid-flight.
        if self._recognizer is None:
            self.load()
        recognizer = self._recognizer
        if recognizer is None:
            raise RuntimeError("SFSpeechRecognizer not loaded")

        mod = _speech()
        assert mod is not None

        request = mod.request_cls.alloc().init()
        request.setShouldReportPartialResults_(False)
        if hasattr(request, "setRequiresOnDeviceRecognition_"):
            request.setRequiresOnDeviceRecognition_(True)
        if hasattr(request, "setTaskHint_"):
            try:
                request.setTaskHint_(_TASK_HINT_DICTATION)
            except Exception:
                pass

        done = threading.Event()
        out: dict[str, Any] = {"text": "", "segments": [], "error": None, "confidence": 0.0}

        def handler(result, error):  # type: ignore[no-untyped-def]
            # Ignore late callbacks after timeout: prevents mutating `out`
            # after we've returned to the caller, and lets the captured
            # closure (task / request) drop sooner.
            if done.is_set():
                return
            try:
                if error is not None:
                    out["error"] = str(error)
                    done.set()
                    return
                if result is None:
                    return
                if result.isFinal():
                    transcription = result.bestTranscription()
                    out["text"] = str(transcription.formattedString())
                    segments, avg_conf = self._segments_from_transcription(transcription)
                    out["segments"] = segments
                    out["confidence"] = avg_conf
                    done.set()
            except Exception:
                log.exception("SFSpeech handler crashed")
                done.set()

        t0 = time.monotonic()
        task = recognizer.recognitionTaskWithRequest_resultHandler_(request, handler)
        try:
            try:
                buf = self._make_buffer(audio)
                request.appendAudioPCMBuffer_(buf)
                request.endAudio()
                if not done.wait(timeout=self._timeout_s):
                    raise TimeoutError("SFSpeechRecognizer timed out")
            except BaseException:
                # Any error path (timeout, buffer alloc failure, ObjC bridge
                # crash) MUST tell the still-running handler to bail and
                # cancel the task — otherwise it lingers, retains the closure,
                # and may try to mutate `out` after we've raised.
                done.set()
                try:
                    task.cancel()
                except Exception:
                    pass
                raise
        finally:
            duration_ms = (time.monotonic() - t0) * 1000.0

        if out["error"]:
            raise RuntimeError(f"SFSpeechRecognizer error: {out['error']}")

        return {
            "text": (out["text"] or "").strip(),
            "confidence": float(out["confidence"]),
            "segments": out["segments"],
            "duration_ms": duration_ms,
        }

    def transcribe_partial(
        self,
        audio: np.ndarray,  # noqa: ARG002
        initial_prompt: str | None = None,  # noqa: ARG002
    ) -> str:
        # Not supported in v1.
        return ""

    def meets_confidence(self, result: dict[str, Any]) -> bool:
        # Apple confidences are in [0, 1]; we accept anything we got back.
        return bool(result.get("text"))

    def reload(self) -> None:
        with self._lock:
            self._recognizer = None
