from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from dictate import cleanup as cleanup_mod
from dictate.cleanup import CleanupClient
from dictate.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = Config(root=tmp_path)
    cfg.presets = {"default": {"system": "clean {vocab}"}}
    cfg.settings = {
        "cleanup": {
            "backend": "ollama",
            "fallback_chain": ["ollama", "raw"],
            "stream": False,
            "timeout_seconds": 8,
        }
    }
    cfg.backends_raw = {
        "ollama": {
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key_env": None,
            "default_model": "qwen2.5:3b-instruct",
            "redact": False,
        }
    }
    return cfg


@pytest.mark.asyncio
async def test_ollama_circuit_opens_after_three_failures_and_closes_on_success(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 100.0

    def monotonic() -> float:
        return now

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "cleaned text"}}]}

    class FakeAsyncClient:
        calls = 0

        def __init__(self, *, timeout: float, verify: bool = True) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:  # noqa: A002
            type(self).calls += 1
            if type(self).calls <= 3:
                raise httpx.TimeoutException("ollama timed out")
            return FakeResponse()

    monkeypatch.setattr(cleanup_mod.time, "monotonic", monotonic)
    monkeypatch.setattr(cleanup_mod.httpx, "AsyncClient", FakeAsyncClient)

    client = CleanupClient(config)
    for _ in range(3):
        text, metrics = await client.clean("raw text", "default", [])
        assert text == "raw text"
        assert metrics["backend"] == "raw"

    assert client._circuit_for("ollama").is_open is True

    text, metrics = await client.clean("raw text", "default", [])
    assert text == "raw text"
    assert metrics["backend"] == "raw"
    assert FakeAsyncClient.calls == 3

    now = 161.0
    text, metrics = await client.clean("raw text", "default", [])
    assert text == "cleaned text"
    assert metrics["backend"] == "ollama"
    assert client._circuit_for("ollama").is_open is False
