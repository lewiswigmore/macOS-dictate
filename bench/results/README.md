# Benchmark results

Write local JSON benchmark outputs here, for example:

```bash
python3 bench/bench_asr.py --json > bench/results/asr-m2-pro-small.json
python3 bench/bench_pipeline.py --json > bench/results/pipeline-m2-pro-small.json
```

JSON files in this directory are gitignored. Each output includes benchmark name, model, backend, device, audio path and duration, run count, latency summaries, RTF, and peak RSS.

See [`../README.md`](../README.md) for the contributor PR submission template.
