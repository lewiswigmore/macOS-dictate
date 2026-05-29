from __future__ import annotations

import re
from typing import TYPE_CHECKING

from dictate.logging_setup import get_logger

if TYPE_CHECKING:
    from dictate.config import BackendSpec

log = get_logger(__name__)


class Redactor:
    def __init__(self, patterns: list[dict]) -> None:
        self._patterns = patterns
        self._compiled: list[tuple[str, re.Pattern[str]]] | None = None

    def _compile(self) -> list[tuple[str, re.Pattern[str]]]:
        if self._compiled is not None:
            return self._compiled
        result: list[tuple[str, re.Pattern[str]]] = []
        for p in self._patterns:
            name: str = p["name"]
            pat: str = p["pattern"]
            if pat.startswith("(?-i)"):
                flags = 0
                pat = pat[5:]
            else:
                flags = re.IGNORECASE
            result.append((name, re.compile(pat, flags)))
        self._compiled = result
        return result

    def redact(self, text: str) -> tuple[str, list[dict]]:
        stats: dict[str, dict] = {}
        for name, rx in self._compile():
            matches = list(rx.finditer(text))
            if not matches:
                continue
            stats[name] = {"name": name, "count": len(matches)}
            text = rx.sub(f"«REDACTED:{name}»", text)
        return text, list(stats.values())

    def redact_pairs(self, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [(self.redact(u)[0], self.redact(a)[0]) for u, a in pairs]


def should_redact_for_backend(backend_spec: BackendSpec) -> bool:
    return backend_spec.redact
