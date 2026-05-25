from __future__ import annotations

import re
from pathlib import Path

from dictate.logging_setup import get_logger

log = get_logger(__name__)

_SEPARATOR = "->"


def load(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return table
    except OSError as exc:
        log.warning("failed to load replacements from %s: %s", path, exc)
        return table

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _SEPARATOR not in stripped:
            log.warning("skipping malformed replacement at %s:%d", path, line_no)
            continue
        source, target = (part.strip() for part in stripped.split(_SEPARATOR, 1))
        if not source or not target:
            log.warning("skipping empty replacement at %s:%d", path, line_no)
            continue
        table[source] = target
    return table


def apply(text: str, table: dict[str, str]) -> str:
    result = text
    for source, target in sorted(table.items(), key=lambda item: (-len(item[0]), item[0].lower())):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(target, result)
    return result
