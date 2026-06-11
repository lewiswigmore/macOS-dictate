from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float
    language: str | None = None


class ParakeetBackend:
    """NVIDIA Parakeet ASR backend for Apple Silicon via parakeet-mlx.

    Install: pip install parakeet-mlx

    Models available at: https://huggingface.co/collections/mlx-community/parakeet
    Defaults to mlx-community/parakeet-tdt-0.6b-v3.

    Parakeet (TDT/CTC) does not expose per-token log-probabilities the way
    Whisper does, so confidence is reported as 1.0 and ``meets_confidence``
    falls back to a non-empty-text check (mirroring the Apple backend).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: Any | None = None

    @staticmethod
    def is_available() -> bool:
        try:
            import parakeet_mlx  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_loaded(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from parakeet_mlx import from_pretrained
        except ImportError as e:
            raise RuntimeError(
                "parakeet-mlx not installed. Install with: pip install parakeet-mlx"
            ) from e
        self._model = from_pretrained(self.model_name)
        log.info("Parakeet ready: model=%s", self.model_name)
        return self._model

    def load(self) -> None:
        self._ensure_loaded()

    def transcribe(
        self,
        audio: bytes | np.ndarray,
        *,
        sample_rate: int = 16000,  # noqa: ARG002 - parakeet expects 16 kHz mono; dictate's pipeline already provides it
    ) -> TranscriptionResult:
        model = self._ensure_loaded()
        import mlx.core as mx
        import numpy as np
        from parakeet_mlx.audio import get_logmel

        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        # parakeet-mlx runs in bfloat16; its own load_audio() casts to bfloat16
        # before get_logmel, so match that to avoid a dtype mismatch in the encoder.
        mel = get_logmel(mx.array(audio).astype(mx.bfloat16), model.preprocessor_config)
        alignments = model.generate(mel)
        text = (alignments[0].text if alignments else "").strip()
        return TranscriptionResult(text=text, confidence=1.0, language="en")

    def meets_confidence(self, result: TranscriptionResult, threshold: float) -> bool:  # noqa: ARG002
        return bool(result.text)
