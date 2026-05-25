"""Spike: feed a tiny audio buffer to SFSpeechRecognizer on-device, sync.

Throwaway script — proves the PyObjC plumbing before we wire it into ASR.

Usage:
    .venv/bin/python scripts/spike_sfspeech.py [path/to/wav]

If no path is given, generates 1 s of silence (should yield empty transcript
without crashing — proves auth + buffer path).
"""

from __future__ import annotations

import sys
import threading
import time
import wave

import numpy as np
from AVFoundation import AVAudioFormat, AVAudioPCMBuffer
from Speech import (
    SFSpeechAudioBufferRecognitionRequest,
    SFSpeechRecognizer,
    SFSpeechRecognizerAuthorizationStatusAuthorized,
)


def request_auth() -> int:
    from Foundation import NSDate, NSRunLoop

    done = threading.Event()
    result = {"status": None}

    def handler(status):
        result["status"] = int(status)
        done.set()

    SFSpeechRecognizer.requestAuthorization_(handler)
    # The handler is dispatched to the main queue → we must drive the run
    # loop here for it to fire. Spin in short slices for up to 30 s so the
    # user has time to dismiss the macOS permission prompt.
    deadline = time.monotonic() + 30
    while not done.is_set() and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    return result["status"] if result["status"] is not None else -1


def load_audio(path: str | None) -> tuple[np.ndarray, int]:
    if not path:
        return np.zeros(16000, dtype=np.float32), 16000
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            arr = arr.reshape(-1, 2).mean(axis=1)
    return arr, sr


def make_pcm_buffer(samples: np.ndarray, sample_rate: int) -> AVAudioPCMBuffer:
    fmt = AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
        1, float(sample_rate), 1, False
    )
    n = len(samples)
    buf = AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(fmt, n)
    if buf is None:
        raise RuntimeError("AVAudioPCMBuffer init failed")
    buf.setFrameLength_(n)
    chan = buf.floatChannelData()
    if chan is None:
        raise RuntimeError("floatChannelData is None")
    chan[0][:n] = samples.astype(np.float32)
    return buf


def transcribe(samples: np.ndarray, sample_rate: int) -> dict:
    recognizer = SFSpeechRecognizer.alloc().init()
    if recognizer is None or not recognizer.isAvailable():
        return {"error": "recognizer unavailable"}

    if hasattr(recognizer, "setRequiresOnDeviceRecognition_"):
        recognizer.setRequiresOnDeviceRecognition_(True)

    request = SFSpeechAudioBufferRecognitionRequest.alloc().init()
    request.setShouldReportPartialResults_(False)
    if hasattr(request, "setRequiresOnDeviceRecognition_"):
        request.setRequiresOnDeviceRecognition_(True)

    done = threading.Event()
    out: dict = {"text": None, "error": None}

    def handler(result, error):
        if error is not None:
            out["error"] = str(error)
            done.set()
            return
        if result is None:
            return
        if result.isFinal():
            out["text"] = str(result.bestTranscription().formattedString())
            done.set()

    t0 = time.monotonic()
    task = recognizer.recognitionTaskWithRequest_resultHandler_(request, handler)

    buf = make_pcm_buffer(samples, sample_rate)
    request.appendAudioPCMBuffer_(buf)
    request.endAudio()

    # Same as for auth: SFSpeech delivers the result handler on the main
    # queue, so a standalone script must spin the run loop to receive it.
    from Foundation import NSDate, NSRunLoop

    deadline = time.monotonic() + 15
    while not done.is_set() and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    if not done.is_set():
        try:
            task.cancel()
        except Exception:
            pass
        out["error"] = "timeout"
    print(f"elapsed during recognition: {(time.monotonic() - t0) * 1000:.0f} ms")
    return out


def main() -> int:
    print("Requesting Speech permission…", flush=True)
    status = request_auth()
    print(f"  status = {status}")
    if status != SFSpeechRecognizerAuthorizationStatusAuthorized:
        print("Not authorized; cannot continue.")
        return 1

    path = sys.argv[1] if len(sys.argv) > 1 else None
    samples, sr = load_audio(path)
    print(f"Loaded {len(samples)} samples @ {sr} Hz")
    t0 = time.monotonic()
    result = transcribe(samples, sr)
    elapsed = (time.monotonic() - t0) * 1000
    print(f"Recognition: {result}  ({elapsed:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
