from __future__ import annotations

import threading
import time
from collections.abc import Callable

import httpx

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)


class HealthMonitor:
    def __init__(
        self,
        config: Config,
        on_change: Callable[[dict], None] | None = None,
    ) -> None:
        self._config = config
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._unhealthy_since: dict[str, float] = {}

        self.status: dict[str, dict] = {
            name: {"ok": False, "latency_ms": 0, "last_check": 0.0, "error": "not checked yet"}
            for name in config.backends_raw
        }

    def _ping(self, name: str) -> None:
        backend = self._config.backend(name)

        if not backend.has_api_key:
            old_ok = self.status[name].get("ok", True)
            self.status[name] = {
                "ok": False,
                "latency_ms": 0,
                "last_check": time.time(),
                "error": "no api key",
            }
            if old_ok and self._on_change:
                self._on_change(self.status)
            return

        t0 = time.monotonic()
        ok = False
        error: str | None = None
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(backend.health_url, headers=backend.auth_headers())
                ok = resp.is_success
                if not ok:
                    error = f"HTTP {resp.status_code}"
        except Exception as exc:
            error = str(exc)

        latency_ms = int((time.monotonic() - t0) * 1000)
        old_ok = self.status[name].get("ok")

        self.status[name] = {
            "ok": ok,
            "latency_ms": latency_ms,
            "last_check": time.time(),
            "error": error,
        }

        if ok:
            self._unhealthy_since.pop(name, None)
        elif name not in self._unhealthy_since:
            self._unhealthy_since[name] = time.time()

        if old_ok != ok and self._on_change:
            self._on_change(self.status)

    def _run(self) -> None:
        interval = float(self._config.get("health.interval_seconds", 30))
        while not self._stop_event.is_set():
            for name in self._config.backends_raw:
                try:
                    self._ping(name)
                except Exception as exc:
                    log.error(
                        "health ping error",
                        extra={"extras": {"backend": name, "error": str(exc)}},
                    )
            self._stop_event.wait(interval)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="health-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def ping_once(self, name: str) -> bool:
        """Synchronous one-shot health check. Used by onboarding & manual checks."""
        try:
            self._ping(name)
        except Exception:
            log.exception("ping_once failed for %s", name)
            return False
        return bool(self.status.get(name, {}).get("ok"))

    def pick_active(self) -> str:
        threshold = float(self._config.get("health.unhealthy_threshold_seconds", 60))
        active = self._config.get("cleanup.backend", "ollama")
        chain = self._config.fallback_chain

        if self.status.get(active, {}).get("ok", False):
            return active

        unhealthy_since = self._unhealthy_since.get(active)
        if unhealthy_since is None or (time.time() - unhealthy_since) <= threshold:
            return active

        for name in chain:
            if name == "raw":
                return "raw"
            if name == active:
                continue
            if self.status.get(name, {}).get("ok", False):
                return name

        return "raw"
