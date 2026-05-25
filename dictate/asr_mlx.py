from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mlx-community/whisper-small.en-mlx"


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float
    language: str | None = None


class MLXWhisperBackend:
    """Apple Silicon optimized Whisper backend via mlx-whisper.

    Install: pip install mlx-whisper

    Models available at: https://huggingface.co/mlx-community
    Defaults to mlx-community/whisper-small.en-mlx
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._loaded = False

    @staticmethod
    def is_available() -> bool:
        try:
            import mlx_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            import mlx_whisper  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "mlx-whisper not installed. Install with: pip install mlx-whisper"
            ) from e
        self._loaded = True
        log.info("MLX Whisper ready: model=%s", self.model_name)

    def load(self) -> None:
        self._ensure_loaded()

    def transcribe(
        self,
        audio: bytes | np.ndarray,
        *,
        sample_rate: int = 16000,  # noqa: ARG002 - mlx-whisper expects 16 kHz arrays
    ) -> TranscriptionResult:
        self._ensure_loaded()
        import mlx_whisper
        import numpy as np

        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        result: dict[str, Any] = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model_name,
            verbose=False,
        )
        text = (result.get("text") or "").strip()
        segments = result.get("segments", [])
        if segments:
            logprobs = [s.get("avg_logprob", 0.0) for s in segments]
            avg_lp = sum(logprobs) / len(logprobs)
            confidence = max(0.0, min(1.0, 1.0 + avg_lp / 5.0))
        else:
            confidence = 0.0
        return TranscriptionResult(
            text=text,
            confidence=confidence,
            language=result.get("language"),
        )

    def meets_confidence(self, result: TranscriptionResult, threshold: float) -> bool:
        return result.confidence >= threshold and bool(result.text)
