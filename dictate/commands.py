from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from dictate.logging_setup import get_logger

log = get_logger(__name__)

_STRIP_TAIL = re.compile(r"[.,]\Z")
_SPELL_SEP = re.compile(r"[\s,]+")
_INSERT_HISTORY_MAX = 10


@dataclass
class Command:
    name: str
    action: str
    text: str | None = None
    count: int | None = None


class CommandParser:
    def __init__(self, commands_yaml: list[dict]) -> None:
        self._commands = commands_yaml
        self._compiled: list[tuple[str, str, str | None, re.Pattern[str]]] | None = None
        self._inserted: deque[int] = deque(maxlen=_INSERT_HISTORY_MAX)

    def _compile(self) -> list[tuple[str, str, str | None, re.Pattern[str]]]:
        if self._compiled is not None:
            return self._compiled
        result: list[tuple[str, str, str | None, re.Pattern[str]]] = []
        for cmd in self._commands:
            name = cmd.get("name", "<unnamed>")
            pattern = cmd.get("pattern", "")
            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                log.warning("skipping voice command %r: bad regex %r: %s", name, pattern, exc)
                continue
            result.append((name, cmd["action"], cmd.get("text"), rx))
        self._compiled = result
        return result

    def remember_inserted(self, text: str) -> None:
        if text:
            self._inserted.append(len(text))

    def parse(self, transcript: str) -> Command | None:
        normalized = _STRIP_TAIL.sub("", transcript.strip())
        for name, action, text, rx in self._compile():
            match = rx.search(normalized)
            if not match:
                continue
            if action == "spell_literal":
                spelled = self._parse_spell_literal(match.group(1))
                if spelled is None:
                    return None
                return Command(name=name, action="insert", text=spelled)
            if action == "scratch_last":
                count = self._inserted.pop() if self._inserted else 0
                return Command(name=name, action=action, count=count)
            return Command(name=name, action=action, text=text)
        return None

    @staticmethod
    def _parse_spell_literal(raw: str) -> str | None:
        tokens = [token for token in _SPELL_SEP.split(raw.strip()) if token]
        if not tokens or any(len(token) != 1 or not token.isalpha() for token in tokens):
            return None
        return "".join(tokens).upper()
