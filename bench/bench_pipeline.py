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
    parser = argparse.ArgumentParser(description="Benchmark synthetic dictate pipeline latency.")
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
    parser.add_argument("--runs", type=int, default=5, help="warm pipeline runs (default: 5)")
    parser.add_argument(
        "--cleanup",
        choices=("stub", "ollama"),
        default="stub",
        help="cleanup backend to time (default: stub; ollama uses local Ollama)",
    )
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


def trim_with_vad(audio: Any, config: Any) -> Any:
    try:
        from dictate.vad import VAD
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Could not import VAD: {exc}") from exc
    try:
        vad = VAD(config)
        return vad.trim_silence(audio)
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"VAD failed: {exc}") from exc


def transcribe(model: Any, audio: Any, config: Any) -> str:
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
        return "".join(segment.text for segment in segments_iter).strip()
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Transcription failed: {exc}") from exc


def cleanup(text: str, mode: str, config: Any) -> tuple[str, dict[str, Any]]:
    if mode == "stub":
        return text, {"backend": "stub", "used_fallback": False}

    config.set("cleanup.backend", "ollama")
    config.set("cleanup.fallback_chain", ["ollama", "raw"])
    try:
        from dictate.cleanup import CleanupClient
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Could not import cleanup client: {exc}") from exc

    try:
        return CleanupClient(config).clean_sync(text, "default", [])
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(f"Cleanup failed: {exc}") from exc


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


def time_step(func: Any, *args: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = func(*args)
    return result, time.perf_counter() - started


def run_once(audio_path: Path, model: Any, config: Any, cleanup_mode: str) -> dict[str, Any]:
    audio, audio_load_s = time_step(read_wav, audio_path)
    trimmed, vad_s = time_step(trim_with_vad, audio, config)
    text, asr_s = time_step(transcribe, model, trimmed, config)
    _cleaned, cleanup_s = time_step(cleanup, text, cleanup_mode, config)
    total_s = audio_load_s + vad_s + asr_s + cleanup_s
    return {
        "audio_load_s": audio_load_s,
        "vad_s": vad_s,
        "asr_s": asr_s,
        "cleanup_s": cleanup_s,
        "total_s": total_s,
        "text_chars": len(text),
    }


def summarize_ms(runs: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = [float(run[key]) for run in runs]
    return {"p50": round(median(values) * 1000), "p95": round(percentile(values, 95) * 1000)}


def run() -> dict[str, Any]:
    args = parse_args()
    if args.runs < 1:
        raise BenchmarkError("--runs must be at least 1")

    config = load_config()
    model_name = args.model or str(config.get("asr.model", "small.en"))
    _audio, audio_duration = read_wav(args.audio)
    model, model_load_ms = load_model(model_name, config)

    run_results = [run_once(args.audio, model, config, args.cleanup) for _ in range(args.runs)]
    return {
        "benchmark": "pipeline",
        "model": model_name,
        "backend": "faster-whisper",
        "device": os.environ.get("DICTATE_ASR_DEVICE", "cpu"),
        "audio": str(args.audio),
        "audio_duration_s": audio_duration,
        "runs": args.runs,
        "cleanup": args.cleanup,
        "model_load_ms": model_load_ms,
        "audio_load_ms": summarize_ms(run_results, "audio_load_s"),
        "vad_ms": summarize_ms(run_results, "vad_s"),
        "asr_ms": summarize_ms(run_results, "asr_s"),
        "cleanup_ms": summarize_ms(run_results, "cleanup_s"),
        "end_to_end_ms": summarize_ms(run_results, "total_s"),
        "rtf": median([run["total_s"] for run in run_results]) / audio_duration if audio_duration else 0.0,
        "peak_rss_mb": peak_rss_mb(),
        "json": args.json,
    }


def print_human(result: dict[str, Any]) -> None:
    print("dictate pipeline benchmark")
    print("--------------------------")
    print(f"Model:        {result['model']} ({result['backend']})")
    print(f"Device:       {result['device']} (set DICTATE_ASR_DEVICE=mps to override)")
    print(f"Audio:        {result['audio']} ({result['audio_duration_s']:.1f}s)")
    print(f"Runs:         {result['runs']}")
    print(f"Cleanup:      {result['cleanup']}")
    print()
    print(f"Model load:   {result['model_load_ms']} ms")
    print(
        f"End-to-end:   p50={result['end_to_end_ms']['p50']}ms  "
        f"p95={result['end_to_end_ms']['p95']}ms"
    )
    print(
        f"Stages p50:   audio_load={result['audio_load_ms']['p50']}ms  "
        f"vad={result['vad_ms']['p50']}ms  asr={result['asr_ms']['p50']}ms  "
        f"cleanup={result['cleanup_ms']['p50']}ms"
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
