from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from dictate.config import Config
from dictate.logging_setup import get_logger

if TYPE_CHECKING:
    import numpy as np
    from faster_whisper import WhisperModel as _WhisperModel

log = get_logger(__name__)


class ASR:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._model: _WhisperModel | None = None
        self._models_dir = config.models_dir / "whisper"
        self._backend: str = self._resolve_backend(config.get("asr.backend", "faster-whisper"))
        self._model_name: str = config.get("asr.model", "distil-medium.en")
        self._loaded_model_name: str | None = None
        self._compute_type: str = config.get("asr.compute_type", "int8")
        self._language: str | None = config.get("asr.language", "en") or None
        self._beam_partial: int = config.get("asr.beam_partial", 1)
        self._beam_final: int = config.get("asr.beam_final", 5)
        self._confidence_min: float = config.get("asr.confidence_min", -1.0)
        self._initial_prompt_from_vocab: bool = config.get("asr.initial_prompt_from_vocab", True)
        # Serialize concurrent loads (pipeline + background prewarm) so we
        # never run two HF downloads or instantiate two WhisperModels in
        # parallel for the same target.
        self._load_lock = threading.Lock()
        self._apple: Any | None = None  # lazy-built AppleASR delegate
        self._mlx: Any | None = None
        self._parakeet: Any | None = None

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        if backend == "mlx":
            from dictate.asr_mlx import MLXWhisperBackend

            if MLXWhisperBackend.is_available():
                return "mlx"
            log.error(
                "mlx-whisper not installed. Install with: pip install mlx-whisper; "
                "falling back to faster-whisper"
            )
            return "faster-whisper"
        if backend == "parakeet":
            from dictate.asr_parakeet import ParakeetBackend

            if ParakeetBackend.is_available():
                return "parakeet"
            log.error(
                "parakeet-mlx not installed. Install with: pip install parakeet-mlx; "
                "falling back to faster-whisper"
            )
            return "faster-whisper"
        return backend

    @property
    def backend(self) -> str:
        return self._backend

    def _is_apple(self) -> bool:
        return self._backend == "apple"

    def _is_mlx(self) -> bool:
        return self._backend == "mlx"

    def _is_parakeet(self) -> bool:
        return self._backend == "parakeet"

    def _ensure_apple(self) -> Any:
        from dictate.asr_apple import AppleASR

        if self._apple is None:
            self._apple = AppleASR(self._config)
        return self._apple

    def _ensure_mlx(self) -> Any:
        from dictate.asr_mlx import DEFAULT_MODEL, MLXWhisperBackend

        if self._mlx is None:
            model_name = self._config.get("asr.mlx.model", DEFAULT_MODEL) or DEFAULT_MODEL
            self._mlx = MLXWhisperBackend(model_name=model_name)
        return self._mlx

    def _ensure_parakeet(self) -> Any:
        from dictate.asr_parakeet import DEFAULT_MODEL, ParakeetBackend

        if self._parakeet is None:
            model_name = self._config.get("asr.parakeet.model", DEFAULT_MODEL) or DEFAULT_MODEL
            self._parakeet = ParakeetBackend(model_name=model_name)
        return self._parakeet

    def load(self) -> None:
        """Pre-warm whichever backend is active. Idempotent + thread-safe."""
        if self._is_apple():
            self._ensure_apple().load()
            return
        if self._is_mlx():
            self._ensure_mlx().load()
            return
        if self._is_parakeet():
            self._ensure_parakeet().load()
            return
        with self._load_lock:
            if self._model is None or self._loaded_model_name != self._model_name:
                self._load_model_locked()

    def reload(self) -> None:
        """Re-read backend + model from config.

        For faster-whisper: does NOT clear the currently-loaded model — that
        would block the next transcribe on the new model's download
        (potentially 10–30 s). Instead the active model keeps serving until
        the next ``load()`` call (typically from a background pre-warm
        thread) successfully swaps in the new one. If the new download
        fails, the old model stays active.

        For apple: drops the cached recognizer; next ``load()`` rebuilds it.
        """
        old_backend = self._backend
        self._backend = self._resolve_backend(self._config.get("asr.backend", "faster-whisper"))
        self._model_name = self._config.get("asr.model", "distil-medium.en")
        self._compute_type = self._config.get("asr.compute_type", "int8")
        self._language = self._config.get("asr.language", "en") or None
        if old_backend != self._backend:
            log.info("ASR backend changed: %s → %s", old_backend, self._backend)
            if self._apple is not None:
                self._apple.reload()
            if self._mlx is not None:
                self._mlx = None
            if self._parakeet is not None:
                self._parakeet = None
        log.info(
            "ASR reload requested; backend=%s target=%s (current=%s)",
            self._backend,
            self._model_name,
            self._loaded_model_name,
        )

    def _load_model_locked(self) -> None:
        """Load (or swap in) the model named in self._model_name.

        Caller must hold ``self._load_lock``. On success the new model
        replaces the old one atomically. On failure the old model is kept so
        the pipeline keeps working with whatever it had.
        """
        from faster_whisper import WhisperModel  # lazy: keep import-time free of heavy deps

        target = self._model_name
        log.info(
            "loading whisper model",
            extra={"extras": {"model": target, "compute_type": self._compute_type}},
        )
        self._models_dir.mkdir(parents=True, exist_ok=True)
        try:
            new_model = WhisperModel(
                target,
                compute_type=self._compute_type,
                download_root=str(self._models_dir),
            )
        except Exception:
            log.exception(
                "failed to load whisper model %r — keeping previous model %r active",
                target,
                self._loaded_model_name,
            )
            raise
        self._model = new_model
        self._loaded_model_name = target

    @property
    def _whisper(self) -> _WhisperModel:
        # Fast path: model already loaded and matches config. No lock.
        if self._model is not None and self._loaded_model_name == self._model_name:
            return self._model
        with self._load_lock:
            if self._model is None or self._loaded_model_name != self._model_name:
                try:
                    self._load_model_locked()
                except Exception:
                    if self._model is not None:
                        # Fall back to whatever model is currently loaded so
                        # the user's recording still produces a transcript.
                        return self._model
                    raise
            return self._model  # type: ignore[return-value]

    def transcribe_final(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        if self._is_apple():
            return self._ensure_apple().transcribe_final(
                audio, initial_prompt=initial_prompt, language=language
            )
        if self._is_mlx():
            t0 = time.monotonic()
            result = self._ensure_mlx().transcribe(
                audio,
                sample_rate=int(self._config.get("audio.sample_rate", 16000)),
            )
            return {
                "text": result.text,
                "confidence": result.confidence,
                "segments": [],
                "duration_ms": (time.monotonic() - t0) * 1000.0,
                "language": result.language,
            }
        if self._is_parakeet():
            t0 = time.monotonic()
            result = self._ensure_parakeet().transcribe(
                audio,
                sample_rate=int(self._config.get("audio.sample_rate", 16000)),
            )
            return {
                "text": result.text,
                "confidence": result.confidence,
                "segments": [],
                "duration_ms": (time.monotonic() - t0) * 1000.0,
                "language": result.language,
            }
        t0 = time.monotonic()
        segments_iter, _info = self._whisper.transcribe(
            audio,
            language=language or self._language,
            beam_size=self._beam_final,
            initial_prompt=initial_prompt,
            condition_on_previous_text=True,
            vad_filter=False,
            temperature=0,
        )
        segments: list[dict[str, Any]] = []
        total_logprob = 0.0
        for seg in segments_iter:
            segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "avg_logprob": seg.avg_logprob,
                }
            )
            total_logprob += seg.avg_logprob

        confidence = total_logprob / len(segments) if segments else 0.0
        text = "".join(s["text"] for s in segments).strip()
        return {
            "text": text,
            "confidence": confidence,
            "segments": segments,
            "duration_ms": (time.monotonic() - t0) * 1000.0,
        }

    def transcribe_partial(
        self,
        audio: np.ndarray,
        initial_prompt: str | None = None,
    ) -> str:
        if self._is_apple():
            return self._ensure_apple().transcribe_partial(audio, initial_prompt=initial_prompt)
        if self._is_mlx():
            return ""
        if self._is_parakeet():
            return ""
        segments_iter, _info = self._whisper.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_partial,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            vad_filter=False,
            temperature=0,
        )
        return "".join(seg.text for seg in segments_iter).strip()

    def meets_confidence(self, result: dict[str, Any]) -> bool:
        if self._is_apple():
            return self._ensure_apple().meets_confidence(result)
        if self._is_mlx():
            from dictate.asr_mlx import TranscriptionResult

            transcription = TranscriptionResult(
                text=str(result.get("text", "")),
                confidence=float(result.get("confidence", 0.0)),
                language=result.get("language"),
            )
            return self._ensure_mlx().meets_confidence(transcription, self._confidence_min)
        if self._is_parakeet():
            from dictate.asr_parakeet import TranscriptionResult

            transcription = TranscriptionResult(
                text=str(result.get("text", "")),
                confidence=float(result.get("confidence", 0.0)),
                language=result.get("language"),
            )
            return self._ensure_parakeet().meets_confidence(transcription, self._confidence_min)
        return float(result["confidence"]) >= self._confidence_min
