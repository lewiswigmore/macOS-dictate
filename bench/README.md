# Benchmarks

This directory contains standalone benchmark scripts for measuring dictate on your own hardware. They are not pytest tests and do not collect or upload telemetry.

## What is measured

- **ASR model load time**: cold `faster-whisper` initialization time.
- **Transcription latency**: warm ASR latency on a fixture WAV, reported as p50/p95 across runs.
- **RTF (real-time factor)**: `transcription_time / audio_duration`; lower is better, and `<1.0` means faster than realtime.
- **Cleanup latency**: synthetic pipeline cleanup step timing, stubbed by default or local Ollama with `--cleanup ollama`.
- **End-to-end latency**: synthetic audio_load → VAD → ASR → cleanup → done, reported as p50/p95.
- **Peak RSS**: process peak resident set size from `resource.getrusage(RUSAGE_SELF).ru_maxrss`.

## Setup

Create a small 16 kHz mono WAV fixture first. See [`fixtures/README.md`](./fixtures/README.md). By default the scripts look for `bench/fixtures/jfk.wav`.

## Run

```bash
python3 bench/bench_asr.py --model small --audio bench/fixtures/jfk.wav --runs 5
python3 bench/bench_pipeline.py --model small --audio bench/fixtures/jfk.wav --runs 5
```

Use the configured ASR model by omitting `--model`. Set `DICTATE_ASR_DEVICE=mps` to try a non-default faster-whisper device on supported installs.

Machine-readable output can be written under `bench/results/`:

```bash
python3 bench/bench_asr.py --json > bench/results/asr-m2-pro-small.json
python3 bench/bench_pipeline.py --json > bench/results/pipeline-m2-pro-small.json
```

`bench/results/*.json` is gitignored so local measurements do not get committed accidentally.

## Publishing results

To share hardware results, run both benchmarks, then submit a PR adding a short summary table row to this README (or to project docs when available). Include the exact command, model, OS, chip, RAM, and whether you used CPU or MPS.

| Hardware | macOS | Python | Model | Device | Audio | Runs | ASR load | ASR p50 / p95 | ASR RTF | Pipeline p50 / p95 | Cleanup | Peak RSS | Notes |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---|
| Apple M2 Pro, 16 GB | 14.6 | 3.11 | small | cpu | jfk.wav (11s) | 5 | 1240 ms | 820 / 890 ms | 0.075 | 980 / 1100 ms | stub | 412 MB | example only |
