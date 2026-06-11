#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import resource
import sys
import time
import wave
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_AUDIO = Path("bench/fixtures/jfk.wav")
MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3")
SAMPLE_RATE = 16_000


class BenchmarkError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark dictate ASR latency and throughput.")
    parser.add_argument(
        "--model",
        choices=MODEL_CHOICES,
        default=None,
        help="faster-whisper model to benchmark (default: config asr.model)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=DEFAULT_AUDIO,
        help="16 kHz mono WAV fixture (default: bench/fixtures/jfk.wav)",
    )
    parser.add_argument("--runs", type=int, default=5, help="warm transcription runs (default: 5)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args()


def load_config() -> Any:
    try:
        from dictate.config import load_config as load_dictate_config
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Could not import dictate config: {exc}") from exc
    return load_dictate_config(REPO_ROOT)


def read_wav(path: Path) -> tuple[Any, float]:
    try:
        import numpy as np
    except ImportError as exc:
        raise BenchmarkError("numpy is required. Install project dependencies first.") from exc

    if not path.exists():
        raise BenchmarkError(
            f"Audio fixture not found: {path}. See bench/fixtures/README.md to create one."
        )

    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            raw = wav.readframes(frames)
    except wave.Error as exc:
        raise BenchmarkError(f"Could not read WAV file {path}: {exc}") from exc

    if channels != 1 or sample_rate != SAMPLE_RATE or sample_width not in {2, 4}:
        raise BenchmarkError(
            f"Expected 16 kHz mono PCM WAV; got {sample_rate} Hz, {channels} channels, "
            f"{sample_width * 8}-bit samples."
        )

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    return audio, frames / sample_rate


def load_model(model_name: str, config: Any) -> tuple[Any, int]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise BenchmarkError(
            "faster-whisper is not installed. Run ./install.sh or install project dependencies."
        ) from exc

    compute_type = str(config.get("asr.compute_type", "int8"))
    device = os.environ.get("DICTATE_ASR_DEVICE", "cpu")
    models_dir = config.models_dir / "whisper"
    models_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        model = WhisperModel(
            model_name,
            compute_type=compute_type,
            device=device,
            download_root=str(models_dir),
        )
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(
            f"Could not load faster-whisper model {model_name!r} on {device!r}: {exc}"
        ) from exc
    return model, round((time.perf_counter() - started) * 1000)


def transcribe(model: Any, audio: Any, config: Any) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        segments_iter, _info = model.transcribe(
            audio,
            language=config.get("asr.language", "en") or None,
            beam_size=int(config.get("asr.beam_final", 5)),
            initial_prompt=None,
            condition_on_previous_text=True,
            vad_filter=False,
            temperature=0,
        )
        text = "".join(segment.text for segment in segments_iter).strip()
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Transcription failed: {exc}") from exc
    return text, time.perf_counter() - started


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil((pct / 100.0) * len(values)) - 1)
    return sorted(values)[index]


def peak_rss_mb() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(rss / (1024 * 1024))
    return round(rss / 1024)


def run() -> dict[str, Any]:
    args = parse_args()
    if args.runs < 1:
        raise BenchmarkError("--runs must be at least 1")

    config = load_config()
    model_name = args.model or str(config.get("asr.model", "distil-medium.en"))
    audio_path = args.audio
    audio, audio_duration = read_wav(audio_path)
    model, model_load_ms = load_model(model_name, config)

    durations: list[float] = []
    last_text = ""
    for _ in range(args.runs):
        last_text, elapsed = transcribe(model, audio, config)
        durations.append(elapsed)

    p50 = median(durations)
    p95 = percentile(durations, 95)
    return {
        "benchmark": "asr",
        "model": model_name,
        "backend": "faster-whisper",
        "device": os.environ.get("DICTATE_ASR_DEVICE", "cpu"),
        "audio": str(audio_path),
        "audio_duration_s": audio_duration,
        "runs": args.runs,
        "model_load_ms": model_load_ms,
        "transcribe_p50_ms": round(p50 * 1000),
        "transcribe_p95_ms": round(p95 * 1000),
        "rtf": p50 / audio_duration if audio_duration else 0.0,
        "peak_rss_mb": peak_rss_mb(),
        "text_chars": len(last_text),
        "json": args.json,
    }


def print_human(result: dict[str, Any]) -> None:
    print("dictate ASR benchmark")
    print("---------------------")
    print(f"Model:        {result['model']} ({result['backend']})")
    print(f"Device:       {result['device']} (set DICTATE_ASR_DEVICE=mps to override)")
    print(f"Audio:        {result['audio']} ({result['audio_duration_s']:.1f}s)")
    print(f"Runs:         {result['runs']}")
    print()
    print(f"Model load:   {result['model_load_ms']} ms")
    print(
        f"Transcribe:   p50={result['transcribe_p50_ms']}ms  "
        f"p95={result['transcribe_p95_ms']}ms"
    )
    print(f"RTF:          {result['rtf']:.3f}  (lower is better, <1.0 = faster than realtime)")
    print(f"Peak RSS:     {result['peak_rss_mb']} MB")


def main() -> int:
    try:
        result = run()
    except BenchmarkError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if result.pop("json"):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
