"""Unit tests for the Parakeet backend's own transcription logic.

parakeet-mlx (and mlx) are not installed in CI's default test environment, so
these tests inject fake `mlx.core`, `parakeet_mlx`, and `parakeet_mlx.audio`
modules. They exercise ParakeetBackend.transcribe directly (dtype handling and
result parsing), beyond the dispatcher-level coverage in test_asr_dispatch.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gen_text: str = "parakeet hi",
    alignments_nonempty: bool = True,
) -> dict:
    captured: dict = {}

    class _Arr:
        def __init__(self, data) -> None:
            self.data = data
            self.dtype = "float32"

        def astype(self, dt):
            self.dtype = dt
            return self

    mlx = types.ModuleType("mlx")
    mlx_core = types.ModuleType("mlx.core")
    mlx_core.array = lambda data: _Arr(data)
    mlx_core.bfloat16 = "bfloat16"
    mlx_core.Dtype = object
    mlx.core = mlx_core
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", mlx_core)

    class _Aligned:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Model:
        def __init__(self) -> None:
            self.preprocessor_config = types.SimpleNamespace(sample_rate=16000)

        def generate(self, mel, **_kw):
            captured["mel"] = mel
            return [_Aligned(gen_text)] if alignments_nonempty else []

    pk = types.ModuleType("parakeet_mlx")
    pk.from_pretrained = lambda name, **_kw: captured.setdefault("model", _Model())

    audio_mod = types.ModuleType("parakeet_mlx.audio")

    def _get_logmel(x, _cfg):
        captured["logmel_input"] = x
        return "MEL"

    audio_mod.get_logmel = _get_logmel
    pk.audio = audio_mod
    monkeypatch.setitem(sys.modules, "parakeet_mlx", pk)
    monkeypatch.setitem(sys.modules, "parakeet_mlx.audio", audio_mod)
    return captured


def test_is_available_true_when_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(monkeypatch)
    from dictate.asr_parakeet import ParakeetBackend

    assert ParakeetBackend.is_available() is True


def test_transcribe_parses_first_alignment_and_casts_bfloat16(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fakes(monkeypatch, gen_text="  hello parakeet  ")
    from dictate.asr_parakeet import ParakeetBackend

    backend = ParakeetBackend(model_name="mlx-community/parakeet-tdt-0.6b-v3")
    result = backend.transcribe(np.zeros(1600, dtype=np.float32))
    assert result.text == "hello parakeet"  # stripped
    assert result.confidence == 1.0
    assert result.language == "en"
    # The audio array must be cast to bfloat16 before get_logmel (matches the
    # dtype parakeet-mlx's own load_audio() uses, avoiding an encoder mismatch).
    assert captured["logmel_input"].dtype == "bfloat16"


def test_transcribe_empty_alignments_returns_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch, alignments_nonempty=False)
    from dictate.asr_parakeet import ParakeetBackend

    backend = ParakeetBackend()
    result = backend.transcribe(np.zeros(800, dtype=np.float32))
    assert result.text == ""


def test_transcribe_accepts_int16_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(monkeypatch)
    from dictate.asr_parakeet import ParakeetBackend

    backend = ParakeetBackend()
    pcm = (np.zeros(320, dtype=np.int16)).tobytes()
    result = backend.transcribe(pcm)
    assert result.text == "parakeet hi"


def test_load_raises_without_parakeet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "parakeet_mlx", None)
    from dictate.asr_parakeet import ParakeetBackend

    backend = ParakeetBackend()
    with pytest.raises(RuntimeError, match="parakeet-mlx not installed"):
        backend.load()
