from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import numpy as np

from .logging_setup import get_logger

if TYPE_CHECKING:
    import onnxruntime as ort

    from .config import Config

log = get_logger(__name__)

# Pinned to silero-vad v6.2.1 (released by snakers4/silero-vad). The model is
# fetched once at first launch and verified against MODEL_SHA256 below; an
# upstream rewrite or MITM that doesn't match the pinned hash is rejected.
# The raw URL skips the github.com → raw.githubusercontent.com redirect so
# we can keep `follow_redirects=False` and still fetch in one hop.
_MODEL_TAG = "v6.2.1"
MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/"
    f"{_MODEL_TAG}/src/silero_vad/data/silero_vad.onnx"
)
# sha256(silero_vad.onnx @ v6.2.1) — verified against the local artefact and
# the upstream tagged blob. If silero ships a new model, bump _MODEL_TAG and
# this constant together.
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
# Single permitted host for the download. Combined with follow_redirects=False
# this means a hijacked DNS / MITM / hostile redirect cannot drag us off to
# attacker infrastructure that would then serve a hash-matching but malicious
# ONNX (the hash check is the real defence, this is belt-and-braces).
_ALLOWED_HOST = "raw.githubusercontent.com"
_MODEL_FILENAME = "silero_vad.onnx"

# Silero-vad ONNX requires exactly 512 samples per chunk at 16 kHz (32 ms)
_CHUNK_SAMPLES: int = 512
_SAMPLE_RATE: int = 16000
_CHUNK_MS: float = _CHUNK_SAMPLES / _SAMPLE_RATE * 1000.0  # 32 ms
# Silero v5 (current upstream) expects each 512-sample chunk to be prefixed with
# 64 samples of context (the tail of the previous chunk). Without it the model
# returns near-zero probability for clear speech. v1 (legacy, hidden=64) does
# not use a separate context buffer.
_CONTEXT_SAMPLES: int = 64


def _sha256_file(path: Path) -> str:
    """Return the hex SHA256 of ``path``. ~2 MB file, hashes in well under
    100 ms — cheap enough to run on every load."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_model_url(url: str) -> None:
    """Refuse to fetch anything that isn't an HTTPS URL on the pinned host.

    The hash check is the real integrity gate, but enforcing scheme + host
    catches misconfiguration / accidental redirects / a future code path
    that swaps MODEL_URL out for an attacker-controlled value before the
    request is sent.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"refusing non-https silero-vad URL: {url}")
    if parsed.hostname != _ALLOWED_HOST:
        raise RuntimeError(
            f"refusing silero-vad URL on unexpected host {parsed.hostname!r}; "
            f"expected {_ALLOWED_HOST}"
        )


def _download_model(dest: Path) -> Path:
    """Download silero_vad.onnx to dest and verify its SHA256; returns dest.

    If ``dest`` already exists, the cached file is hashed and reused on a
    match. A stale or tampered cache (e.g. an attacker writing to
    ``~/dictate/models/silero_vad.onnx`` directly) is detected and replaced
    with a fresh, verified copy from the pinned upstream.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        actual = _sha256_file(dest)
        if actual == MODEL_SHA256:
            return dest
        log.warning(
            "silero-vad cache at %s failed SHA256 check (got %s, want %s); "
            "deleting and re-downloading",
            dest,
            actual,
            MODEL_SHA256,
        )
        dest.unlink(missing_ok=True)

    _validate_model_url(MODEL_URL)
    log.info("Downloading silero-vad ONNX model to %s", dest)
    digest = hashlib.sha256()
    # Stream into a sibling tmp file and atomic-rename on success so that a
    # crash mid-download cannot leave a half-written file at the dest path
    # (which the next launch would happily reuse via the cached-load branch).
    tmp = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=dest.parent,
        prefix=f".{dest.name}.",
        suffix=".part",
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        try:
            import httpx

            # follow_redirects=False: the canonical raw URL is a 200 in one
            # hop; any 3xx is unexpected and is treated as an integrity
            # failure rather than silently followed off-host.
            with (
                httpx.Client(follow_redirects=False, timeout=120.0, verify=True) as client,
                client.stream("GET", MODEL_URL) as resp,
            ):
                resp.raise_for_status()
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"silero-vad fetch returned unexpected status "
                        f"{resp.status_code}; refusing to follow redirects."
                    )
                with tmp:
                    for chunk in resp.iter_bytes(65536):
                        digest.update(chunk)
                        tmp.write(chunk)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to download silero-vad model: {exc}\n"
                f"Manual download URL: {MODEL_URL}\n"
                f"Save to:            {dest}"
            ) from exc

        actual = digest.hexdigest()
        if actual != MODEL_SHA256:
            raise RuntimeError(
                f"silero-vad SHA256 mismatch: got {actual}, want {MODEL_SHA256}. "
                f"Refusing to load an unverified ONNX model. Source: {MODEL_URL}"
            )

        os.replace(tmp_path, dest)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    log.info("silero-vad model saved (%d bytes, sha256 verified)", dest.stat().st_size)
    return dest


def _load_session(path: Path) -> ort.InferenceSession:
    try:
        import onnxruntime as ort_mod
    except ImportError as exc:
        raise ImportError("onnxruntime is required for VAD: pip install onnxruntime") from exc
    return ort_mod.InferenceSession(str(path), providers=["CPUExecutionProvider"])


class VAD:
    """
    Streaming voice activity detector backed by silero-vad (ONNX).

    The model processes 512-sample (32 ms) windows at 16 kHz and returns a
    speech probability per window while maintaining LSTM hidden state across
    windows.

    Endpoint detection logic:
        - Once accumulated speech duration ≥ min_speech_ms the utterance is
          considered active.
        - When active and accumulated silence duration ≥ min_silence_ms, an
          endpoint is signalled and state resets.
    """

    def __init__(self, config: Config) -> None:
        self._threshold: float = float(config.get("vad.threshold", 0.5))
        self._min_speech_ms: float = float(config.get("vad.min_speech_ms", 200))
        self._min_silence_ms: float = float(config.get("vad.min_silence_ms", 500))
        self._model_path: Path = config.models_dir / _MODEL_FILENAME

        self._session: ort.InferenceSession | None = None
        # Schema is detected at session-load time. Two known signatures:
        #   v1 (legacy): inputs=[input, sr, h, c], outputs=[output, hn, cn], hidden=64
        #   v2 (current upstream): inputs=[input, state, sr], outputs=[output, stateN], hidden=128
        self._schema: str = "v2"
        self._hidden: int = 128
        self._state: np.ndarray = self._fresh_state()
        # v2 context buffer — last 64 samples of audio fed into the model.
        # Prepended to each new chunk before inference. Reset to zeros on init/reset.
        self._context: np.ndarray = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)
        self._leftover = np.array([], dtype=np.float32)
        self._utterance_started: bool = False
        self._speech_ms: float = 0.0
        self._silence_ms: float = 0.0
        self._last_prob: float = 0.0

    def _fresh_state(self) -> np.ndarray:
        return np.zeros((2, 1, self._hidden), dtype=np.float32)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Pre-warm the ONNX session. Safe to call multiple times."""
        self._ensure_session()

    def reset(self) -> None:
        """Reset LSTM state and endpoint-detection counters."""
        self._state = self._fresh_state()
        self._context = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)
        self._leftover = np.array([], dtype=np.float32)
        self._utterance_started = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._last_prob = 0.0

    def process_chunk(self, audio: np.ndarray) -> dict:
        """
        Feed arbitrary-length float32 audio and return a status dict:
            {prob: float, speech: bool, endpoint: bool}

        Internally buffers leftover samples so caller need not align to 512.
        """
        self._ensure_session()
        audio = np.asarray(audio, dtype=np.float32)

        # Prepend carry-over from previous call
        data = np.concatenate([self._leftover, audio])
        n_full = len(data) // _CHUNK_SAMPLES
        self._leftover = data[n_full * _CHUNK_SAMPLES :]

        if n_full == 0:
            return {"prob": self._last_prob, "speech": False, "endpoint": False}

        endpoint = False
        last_speech = False
        last_prob = self._last_prob

        for i in range(n_full):
            chunk = data[i * _CHUNK_SAMPLES : (i + 1) * _CHUNK_SAMPLES]
            prob, self._state, self._context = self._infer(chunk, self._state, self._context)
            last_prob = prob
            is_speech = prob >= self._threshold
            last_speech = is_speech

            if is_speech:
                self._speech_ms += _CHUNK_MS
                self._silence_ms = 0.0
                if self._speech_ms >= self._min_speech_ms:
                    self._utterance_started = True
            else:
                if self._utterance_started:
                    self._silence_ms += _CHUNK_MS
                    if self._silence_ms >= self._min_silence_ms:
                        endpoint = True
                        self._utterance_started = False
                        self._speech_ms = 0.0
                        self._silence_ms = 0.0
                else:
                    # No utterance yet; reset speech counter on silence
                    self._speech_ms = 0.0

        self._last_prob = last_prob
        return {"prob": last_prob, "speech": last_speech, "endpoint": endpoint}

    def trim_silence(self, audio: np.ndarray) -> np.ndarray:
        """Remove leading and trailing silent frames from a complete audio buffer.

        Uses a fresh LSTM state so it does not affect streaming state.

        Fallback behaviour: if **no** frame crosses the speech threshold but the
        raw clip is substantial (≥ 0.5 s), we return the raw audio with a
        warning that includes the max observed probability. This prevents the
        common UX failure where a slightly quiet recording is silently dropped
        — better to let ASR have a shot than to give the user zero feedback.
        """
        self._ensure_session()
        audio = np.asarray(audio, dtype=np.float32)
        n_full = len(audio) // _CHUNK_SAMPLES
        if n_full == 0:
            return audio

        h = self._fresh_state()
        ctx = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)
        speech_indices: list[int] = []
        max_prob = 0.0

        for i in range(n_full):
            chunk = audio[i * _CHUNK_SAMPLES : (i + 1) * _CHUNK_SAMPLES]
            prob, h, ctx = self._infer(chunk, h, ctx)
            if prob > max_prob:
                max_prob = prob
            if prob >= self._threshold:
                speech_indices.append(i)

        if not speech_indices:
            # Substantial clip with some signal but nothing crossed the threshold
            # → mic may be quiet or threshold may be too high. Surface this and
            # fall back to raw audio so the user still gets a transcript attempt.
            # Pure silence (max_prob ≈ 0) is still dropped to avoid wasted ASR.
            substantial = len(audio) >= _SAMPLE_RATE // 2  # ≥ 0.5 s
            has_signal = max_prob >= 0.1
            if substantial and has_signal:
                log.warning(
                    "VAD: no frame crossed threshold (max prob %.3f < %.3f); "
                    "passing raw audio to ASR. If this happens often, lower "
                    "vad.threshold in settings.yaml or check your mic input level.",
                    max_prob,
                    self._threshold,
                )
                return audio
            return np.array([], dtype=np.float32)

        first_sample = speech_indices[0] * _CHUNK_SAMPLES
        last_sample = min((speech_indices[-1] + 1) * _CHUNK_SAMPLES, len(audio))
        return audio[first_sample:last_sample]

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def _ensure_session(self) -> None:
        if self._session is None:
            path = _download_model(self._model_path)
            self._session = _load_session(path)
            self._detect_schema()
            # State must be re-allocated with the detected hidden size.
            self._state = self._fresh_state()

    def _detect_schema(self) -> None:
        """Inspect the loaded model and pick the right inference signature."""
        assert self._session is not None
        input_names = {i.name for i in self._session.get_inputs()}
        if "state" in input_names:
            self._schema = "v2"
            state_shape = next(i.shape for i in self._session.get_inputs() if i.name == "state")
            # Shape is [2, batch, hidden]; hidden is the third dim.
            if len(state_shape) >= 3 and isinstance(state_shape[2], int):
                self._hidden = int(state_shape[2])
        elif "h" in input_names and "c" in input_names:
            self._schema = "v1"
            h_shape = next(i.shape for i in self._session.get_inputs() if i.name == "h")
            if len(h_shape) >= 3 and isinstance(h_shape[2], int):
                self._hidden = int(h_shape[2])
        else:
            raise RuntimeError(f"Unknown silero-vad ONNX schema; inputs were {sorted(input_names)}")
        log.debug("silero-vad schema=%s hidden=%d", self._schema, self._hidden)

    def _infer(
        self,
        chunk: np.ndarray,
        state: np.ndarray,
        context: np.ndarray | None = None,
    ) -> tuple[float, np.ndarray, np.ndarray]:
        """Run one 512-sample chunk through silero-vad.

        Handles both the legacy (h/c) and current (state) ONNX signatures
        transparently — schema is detected once at load time.

        For v2 the 64-sample ``context`` (tail of the previous chunk) is
        prepended to the input — silero-v5 requires this or it returns
        near-zero probabilities for clear speech. The returned ``new_context``
        is the last 64 samples of the current chunk, ready to feed the next
        call. ``context=None`` is treated as a fresh zero buffer (entry point).
        For v1 the context is passed through unchanged (legacy models don't
        consume it).
        """
        assert self._session is not None
        if context is None:
            context = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)

        if self._schema == "v2":
            inp = np.concatenate([context, chunk]).reshape(1, -1).astype(np.float32)
            sr = np.array(_SAMPLE_RATE, dtype=np.int64)  # 0-d tensor, not scalar
            out = self._session.run(
                ["output", "stateN"],
                {"input": inp, "state": state, "sr": sr},
            )
            new_context = chunk[-_CONTEXT_SAMPLES:].astype(np.float32, copy=True)
            return float(out[0][0, 0]), out[1], new_context

        # v1: state is treated as h, with a sibling c kept on the instance.
        sr = np.array([_SAMPLE_RATE], dtype=np.int64)
        inp = chunk.reshape(1, -1).astype(np.float32)
        h, c = state, self._fresh_state()
        out = self._session.run(
            ["output", "hn", "cn"],
            {"input": inp, "sr": sr, "h": h, "c": c},
        )
        return float(out[0][0, 0]), out[1], context
