from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from dictate import code_grammar
from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)


class CircuitBreaker:
    def __init__(
        self,
        backend_name: str,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._backend_name = backend_name
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._open_until = 0.0

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def is_open(self) -> bool:
        return self._open_until > time.monotonic()

    def allow_request(self) -> bool:
        return not self.is_open

    def record_success(self) -> None:
        was_open = self._open_until > 0.0 or self._consecutive_failures >= self._failure_threshold
        self._consecutive_failures = 0
        self._open_until = 0.0
        if was_open:
            log.info("cleanup circuit closed for backend %r", self._backend_name)

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._open_until = time.monotonic() + self._cooldown_seconds
            log.warning(
                "cleanup circuit opened for backend %r after %d consecutive failures",
                self._backend_name,
                self._consecutive_failures,
            )


class CleanupClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _build_messages(
        self,
        raw: str,
        preset: str,
        vocab: list[str],
        selection: str | None = None,
        few_shot: list[tuple[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        preset_data = self._config.preset(preset)
        system_text = preset_data.get("system", "").replace("{vocab}", ", ".join(vocab))

        if selection is not None:
            suffix_template = self._config.presets.get("selection_suffix", "")
            system_text += suffix_template.replace("{selection}", selection)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_text}]

        for user_ex, assistant_ex in few_shot or []:
            messages.append({"role": "user", "content": user_ex})
            messages.append({"role": "assistant", "content": assistant_ex})

        messages.append({"role": "user", "content": raw})
        return messages

    async def _stream_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        chunks: list[str] = []
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    content = data["choices"][0]["delta"].get("content")
                    if content:
                        chunks.append(content)
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        return "".join(chunks), {}

    def _circuit_for(self, backend_name: str) -> CircuitBreaker:
        breaker = self._circuit_breakers.get(backend_name)
        if breaker is None:
            breaker = CircuitBreaker(backend_name)
            self._circuit_breakers[backend_name] = breaker
        return breaker

    async def _call_backend(
        self,
        backend_name: str,
        messages: list[dict[str, str]],
        timeout: float,
    ) -> tuple[str, dict[str, Any]]:
        cfg = self._config
        backend = cfg.backend(backend_name)
        backend.ensure_api_key()

        # Model resolution: the user-configured `cleanup.model` only applies to
        # the *primary* backend (`cleanup.backend`). Fallback backends use their
        # own `default_model` from backends.yaml — otherwise we'd POST a model
        # name they don't have (e.g. sending gpt-5.4-mini to a local Ollama)
        # and waste the fallback by triggering a 404.
        primary_backend = cfg.get("cleanup.backend", backend_name)
        if backend_name == primary_backend:
            model = cfg.get("cleanup.model", backend.default_model)
        else:
            model = backend.default_model
        temperature = cfg.get("cleanup.temperature", 0.2)
        max_tokens = cfg.get("cleanup.max_tokens", 800)
        stream = cfg.get("cleanup.stream", True)

        headers = {"Content-Type": "application/json", **backend.auth_headers()}

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        url = backend.url("chat/completions")
        t0 = time.monotonic()

        async with httpx.AsyncClient(timeout=timeout) as client:
            if stream:
                text, _ = await self._stream_response(client, url, headers, payload)
                tokens_in: int | None = None
                tokens_out: int | None = None
            else:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                tokens_in = usage.get("prompt_tokens")
                tokens_out = usage.get("completion_tokens")

        latency_ms = int((time.monotonic() - t0) * 1000)
        metrics: dict[str, Any] = {
            "backend": backend_name,
            "model": model,
            "latency_ms": latency_ms,
            "used_fallback": False,
        }
        if tokens_in is not None:
            metrics["tokens_in"] = tokens_in
        if tokens_out is not None:
            metrics["tokens_out"] = tokens_out

        return text, metrics

    @staticmethod
    def _strip_output(text: str) -> str:
        text = text.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
            text = text[1:-1].strip()
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return text.strip()

    @staticmethod
    def _looks_like_pure_code(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        non_letters = sum(1 for char in stripped if not char.isalpha())
        return non_letters / len(stripped) > 0.30

    def _code_grammar_enabled(self, preset: str) -> bool:
        if not bool(self._config.get("cleanup.code_grammar.enabled", True)):
            return False
        configured = self._config.get("cleanup.code_grammar.presets", ["code"])
        if isinstance(configured, str):
            presets = {configured}
        else:
            presets = {str(item) for item in configured}
        return preset in presets

    async def clean(
        self,
        raw: str,
        preset: str,
        vocab: list[str],
        selection: str | None = None,
        few_shot: list[tuple[str, str]] | None = None,
    ) -> tuple[str, dict]:
        source = raw
        if self._code_grammar_enabled(preset):
            source = code_grammar.transform(raw)
            if self._looks_like_pure_code(source):
                return source, {
                    "used_fallback": False,
                    "backend": "code_grammar",
                    "code_grammar_applied": True,
                    "cleanup_skipped": "pure_code",
                }

        messages = self._build_messages(source, preset, vocab, selection, few_shot)
        total_budget = float(self._config.get("cleanup.timeout_seconds", 8))
        chain = self._config.fallback_chain
        deadline = time.monotonic() + total_budget
        # Per-backend floor: never call a backend with less than this — a
        # too-short timeout is just a guaranteed failure with wasted setup.
        _MIN_BACKEND_TIMEOUT = 0.5

        for i, backend_name in enumerate(chain):
            if backend_name == "raw":
                return source, {"used_fallback": True, "backend": "raw"}
            breaker = self._circuit_for(backend_name)
            if not breaker.allow_request():
                log.warning(
                    "cleanup circuit open for backend %r; skipping to fallback",
                    backend_name,
                    extra={"extras": {"backend": backend_name}},
                )
                continue
            remaining = deadline - time.monotonic()
            if remaining < _MIN_BACKEND_TIMEOUT:
                log.warning(
                    "cleanup budget exhausted before backend %r; skipping",
                    backend_name,
                )
                continue
            try:
                text, metrics = await self._call_backend(backend_name, messages, remaining)
                breaker.record_success()
                text = self._strip_output(text)
                if not text and source:
                    log.warning(
                        "model returned empty; falling back to raw",
                        extra={"extras": {"backend": backend_name}},
                    )
                    return source, {**metrics, "used_fallback": True}
                if i > 0:
                    metrics["used_fallback"] = True
                return text, metrics
            except Exception as exc:
                breaker.record_failure()
                log.warning(
                    "backend %r failed: %s: %s",
                    backend_name,
                    type(exc).__name__,
                    exc,
                    extra={"extras": {"backend": backend_name, "error": str(exc)}},
                )

        log.error("all backends failed; returning raw transcript")
        return source, {"used_fallback": True, "backend": "raw"}

    def clean_sync(
        self,
        raw: str,
        preset: str,
        vocab: list[str],
        selection: str | None = None,
        few_shot: list[tuple[str, str]] | None = None,
    ) -> tuple[str, dict]:
        return asyncio.run(self.clean(raw, preset, vocab, selection, few_shot))
