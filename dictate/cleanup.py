from __future__ import annotations

import asyncio
import json
import re
import secrets
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
        self._ollama_resolution: dict[tuple[str, str], str | None] = {}

    @staticmethod
    def _is_ollama_backend(backend: Any) -> bool:
        base = (backend.base_url or "").lower()
        return ":11434" in base or "ollama" in base

    @staticmethod
    def _pick_best_ollama_model(installed: list[str], configured: str | None) -> str | None:
        if not installed:
            return None
        if configured and configured in installed:
            return configured

        def parse_size_b(name: str) -> float:
            m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", name.lower())
            return float(m.group(1)) if m else 50.0

        def score(name: str) -> tuple[int, float, float]:
            n = name.lower()
            if "embed" in n:
                return (99, 0, 0)
            # Tier: prefer instruct/chat, then known general LLMs, deprioritise coder.
            if "instruct" in n:
                tier = 0
            elif "chat" in n:
                tier = 1
            elif "coder" in n or "code" in n:
                tier = 3
            elif any(p in n for p in ("qwen", "llama", "mistral", "hermes", "phi", "gemma")):
                tier = 2
            else:
                tier = 4
            size_b = parse_size_b(n)
            # Cleanup needs >=3B for reliable grammar-without-summarising.
            # Penalise anything smaller heavily.
            too_small = 0 if size_b >= 3.0 else 1
            # Among >=3B, prefer the smallest (latency); among <3B, prefer the largest.
            size_score = size_b if too_small == 0 else -size_b
            return (too_small, tier, size_score)

        ranked = sorted(installed, key=score)
        return ranked[0]

    @staticmethod
    def _looks_summarised(raw: str, cleaned: str) -> bool:
        """Heuristic: cleaned output is suspiciously shorter than the raw.

        Cleanup removes filler/repeats, so a small shrink (~10-25%) is normal.
        A drop below 50% of input on inputs >80 chars almost always means the
        model summarised, answered, or refused — never legitimate cleanup.
        """
        raw_len = len(raw.strip())
        clean_len = len(cleaned.strip())
        if raw_len < 80:
            return False
        return clean_len < raw_len * 0.5

    @staticmethod
    def _list_ollama_models(base_url: str) -> list[str]:
        """Synchronously list installed Ollama models for dashboard health UI."""
        if not base_url:
            return []
        root = re.sub(r"/v\d+/?$", "", base_url).rstrip("/")
        try:
            with httpx.Client(timeout=2.0, verify=True) as client:
                resp = client.get(f"{root}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            return []
        names = [m.get("name") or m.get("model") for m in data.get("models", [])]
        return [n for n in names if n]

    async def _resolve_ollama_model(self, backend: Any, configured_model: str) -> str:
        if not self._is_ollama_backend(backend):
            return configured_model
        cache_key = (backend.base_url, configured_model)
        if cache_key in self._ollama_resolution:
            cached = self._ollama_resolution[cache_key]
            return cached or configured_model
        # /api/tags lives on the bare Ollama root, not /v1
        root = re.sub(r"/v\d+/?$", "", backend.base_url).rstrip("/")
        tags_url = f"{root}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=2.0, verify=True) as client:
                resp = await client.get(tags_url)
                resp.raise_for_status()
                data = resp.json()
            installed = [m.get("name") or m.get("model") for m in data.get("models", [])]
            installed = [m for m in installed if m]
        except Exception as exc:  # noqa: BLE001
            log.debug("ollama tag lookup failed: %s", exc)
            self._ollama_resolution[cache_key] = None
            return configured_model
        chosen = self._pick_best_ollama_model(installed, configured_model)
        if chosen and chosen != configured_model:
            log.warning(
                "cleanup model %r not installed in Ollama; using %r instead "
                "(available: %s). Run `ollama pull %s` to use the configured model.",
                configured_model,
                chosen,
                ", ".join(installed),
                configured_model,
            )
        self._ollama_resolution[cache_key] = chosen
        return chosen or configured_model

    # Built-in few-shot examples that demonstrate the "preserve verbatim, just
    # tidy" contract. These reinforce the length guard and stop small instruct
    # models from summarising long dictations into a 1-line answer.
    _BUILTIN_FEW_SHOT: tuple[tuple[str, str], ...] = (
        (
            "<DICTATION>\nso um can we do a bit of a better job of making this dashboard "
            "you know more like a real product um with recent chats and health and things "
            "rather than just dropping straight into history because right now it feels a "
            "little bit raw\n</DICTATION>",
            "So, can we do a bit of a better job of making this dashboard more like a real "
            "product, with recent chats and health and things, rather than just dropping "
            "straight into history? Because right now it feels a little bit raw.",
        ),
        (
            "<DICTATION>\nuh remind me to pick up groceries after the gym tomorrow\n</DICTATION>",
            "Remind me to pick up groceries after the gym tomorrow.",
        ),
    )

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
            # Selection comes from the AX API of whatever app is frontmost; any
            # app the user has granted Accessibility to can put arbitrary text
            # there, including text that tries to break out of the SELECTION
            # block and inject new instructions. Fence it with a random nonce
            # and strip closing tags from the selection itself.
            sel_nonce = secrets.token_hex(4)
            sel_open = f"<SELECTION_{sel_nonce}>"
            sel_close = f"</SELECTION_{sel_nonce}>"
            safe_selection = re.sub(
                r"</SELECTION[A-Za-z0-9_]*>", "[/]", selection, flags=re.IGNORECASE
            )
            fenced_selection = f"{sel_open}\n{safe_selection}\n{sel_close}"
            system_text += suffix_template.replace("{selection}", fenced_selection)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_text}]

        # Built-in examples first, then any learned corrections from learn.py.
        # The first example is intentionally long to anchor length preservation.
        if selection is None:
            for user_ex, assistant_ex in self._BUILTIN_FEW_SHOT:
                messages.append({"role": "user", "content": user_ex})
                messages.append({"role": "assistant", "content": assistant_ex})

        for user_ex, assistant_ex in few_shot or []:
            messages.append({"role": "user", "content": user_ex})
            messages.append({"role": "assistant", "content": assistant_ex})

        # Fence the live dictation so the model treats it as data, not as a
        # prompt directed at itself. Critical for small instruct models that
        # would otherwise answer "Can we…" style dictations.
        # Defense in depth: (1) random per-request tag so a malicious dictation
        # cannot predict and close the fence, (2) escape any literal
        # </DICTATION> the user did manage to dictate.
        nonce = secrets.token_hex(4)
        open_tag = f"<DICTATION_{nonce}>"
        close_tag = f"</DICTATION_{nonce}>"
        safe_raw = re.sub(r"</DICTATION[A-Za-z0-9_]*>", "[/]", raw, flags=re.IGNORECASE)
        fenced = f"{open_tag}\n{safe_raw}\n{close_tag}"
        messages.append({"role": "user", "content": fenced})
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
        model = await self._resolve_ollama_model(backend, model)
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

        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
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
                # Summarisation guard: if the cleaned text is dramatically
                # shorter than the input, the model almost certainly summarised
                # or answered the dictation instead of cleaning it. Fall back
                # to the raw transcript so we don't lose user content.
                if self._looks_summarised(source, text):
                    log.warning(
                        "cleanup output looks summarised (%d → %d chars); "
                        "falling back to raw transcript",
                        len(source),
                        len(text),
                        extra={
                            "extras": {
                                "backend": backend_name,
                                "raw_len": len(source),
                                "cleaned_len": len(text),
                            }
                        },
                    )
                    return source, {
                        **metrics,
                        "used_fallback": True,
                        "cleanup_skipped": "summarisation_detected",
                        "backend": "raw",
                    }
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
