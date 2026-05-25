# Benchmark fixtures

Large audio files are not committed to the repository. Create a small public-domain sample locally, or use any 16 kHz mono WAV you want to benchmark.

Example using the JFK sample from OpenAI Whisper:

```bash
curl -L -o bench/fixtures/jfk.flac https://github.com/openai/whisper/raw/main/tests/jfk.flac
ffmpeg -i bench/fixtures/jfk.flac -ar 16000 -ac 1 bench/fixtures/jfk.wav
```

The benchmark scripts default to `bench/fixtures/jfk.wav`.
