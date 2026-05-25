from __future__ import annotations

"""
End-to-end fixture test.

Strategy
--------
* faster-whisper, pyobjc, and other heavy/platform deps are NOT required.
* ASR is replaced by _StubASR — no model, no disk, no inference.
* cleanup.CleanupClient (if present) is tested via a monkeypatched _post so no
  real HTTP is made.  The test is skipped if cleanup.py hasn't been written yet.

What this proves
----------------
  synthetic audio → stub ASR → (optional) stubbed CleanupClient → expected text
"""

import numpy as np
import pytest

from dictate.config import Config

# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

_KNOWN_AUDIO: np.ndarray = np.zeros(16_000, dtype=np.float32)  # 1 s of silence @ 16 kHz
_KNOWN_TRANSCRIPT = "set a timer for five minutes"
_CLEANED_TEXT = "Set a timer for five minutes."


# ---------------------------------------------------------------------------
# Stub ASR — mirrors the real ASR public API without any heavy dependencies
# ---------------------------------------------------------------------------


class _StubASR:
    def __init__(self, config: Config) -> None:  # noqa: ARG002
        pass

    def load(self) -> None:
        pass

    def transcribe_final(
        self,
        audio: np.ndarray,  # noqa: ARG002
        initial_prompt: str | None = None,  # noqa: ARG002
        language: str | None = None,  # noqa: ARG002
    ) -> dict:
        return {
            "text": _KNOWN_TRANSCRIPT,
            "confidence": -0.3,
            "segments": [],
            "duration_ms": 1.0,
        }

    def transcribe_partial(
        self,
        audio: np.ndarray,  # noqa: ARG002
        initial_prompt: str | None = None,  # noqa: ARG002
    ) -> str:
        return _KNOWN_TRANSCRIPT

    def meets_confidence(self, result: dict) -> bool:
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_asr_stub_result_shape() -> None:
    """Stub ASR returns the exact dict shape the real ASR promises."""
    config = Config.load()
    asr = _StubASR(config)

    result = asr.transcribe_final(_KNOWN_AUDIO)

    assert result["text"] == _KNOWN_TRANSCRIPT
    assert "confidence" in result
    assert "segments" in result
    assert "duration_ms" in result
    assert asr.meets_confidence(result)
    assert asr.transcribe_partial(_KNOWN_AUDIO) == _KNOWN_TRANSCRIPT


def test_asr_stub_injected_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patching dictate.asr.ASR replaces the class seen by downstream callers."""
    import dictate.asr as asr_mod

    monkeypatch.setattr(asr_mod, "ASR", _StubASR)

    config = Config.load()
    asr = asr_mod.ASR(config)
    result = asr.transcribe_final(_KNOWN_AUDIO)
    assert result["text"] == _KNOWN_TRANSCRIPT


def test_e2e_asr_to_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Full pipeline: stub ASR → stubbed CleanupClient → cleaned text.

    Skipped automatically when cleanup.py hasn't been implemented yet.
    """
    cleanup_mod = pytest.importorskip(
        "dictate.cleanup",
        reason="dictate.cleanup not yet implemented — skipping e2e pipeline test",
    )

    import dictate.asr as asr_mod

    monkeypatch.setattr(asr_mod, "ASR", _StubASR)

    config = Config.load()
    asr = asr_mod.ASR(config)
    asr_result = asr.transcribe_final(_KNOWN_AUDIO)
    assert asr_result["text"] == _KNOWN_TRANSCRIPT

    CleanupClient = cleanup_mod.CleanupClient

    # Patch _call_backend — the lowest HTTP seam before any real network I/O.
    # Returns (text, metrics) matching CleanupClient's internal contract.
    async def _fake_call_backend(
        self,  # noqa: ANN001
        backend_name: str,  # noqa: ANN001, ARG001
        messages: list,  # noqa: ANN001, ARG001
        timeout: float,  # noqa: ANN001, ARG001
    ) -> tuple[str, dict]:
        return _CLEANED_TEXT, {"backend": "stub", "latency_ms": 0}

    monkeypatch.setattr(CleanupClient, "_call_backend", _fake_call_backend)

    client = CleanupClient(config)
    # clean_sync is the blocking wrapper; avoids needing pytest-asyncio here.
    cleaned, _metrics = client.clean_sync(asr_result["text"], preset="default", vocab=[])
    assert cleaned == _CLEANED_TEXT
