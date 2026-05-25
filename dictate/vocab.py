from __future__ import annotations

from pathlib import Path
from threading import Lock

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

# Process-wide cache: (preset, project) → (max_mtime, terms).
# Vocab files are static config that only changes when the user edits them,
# so we recompute only on actual mtime changes.
_VOCAB_CACHE: dict[tuple[str, str | None], tuple[float, list[str]]] = {}
_VOCAB_LOCK = Lock()


def _candidate_paths(config: Config, preset: str, project: str | None) -> list[Path]:
    vocab_dir = config.root / "config" / "vocab"
    paths: list[Path] = []
    if preset == "code":
        paths.append(vocab_dir / "code.txt")
    paths.append(vocab_dir / "work.txt")
    paths.append(vocab_dir / "personal.txt")
    if project:
        proj_path = vocab_dir / "projects" / f"{project}.txt"
        if proj_path.exists():
            paths.append(proj_path)
    return paths


def _max_mtime(paths: list[Path]) -> float:
    latest = 0.0
    for p in paths:
        try:
            m = p.stat().st_mtime
            if m > latest:
                latest = m
        except OSError:
            continue
    return latest


def load_vocab(config: Config, preset: str, project: str | None = None) -> list[str]:
    paths = _candidate_paths(config, preset, project)
    mtime = _max_mtime(paths)
    key = (preset, project)

    with _VOCAB_LOCK:
        cached = _VOCAB_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    seen: set[str] = set()
    terms: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            continue
        for line in text.splitlines():
            term = line.strip()
            if not term or term.startswith("#"):
                continue
            if term not in seen:
                seen.add(term)
                terms.append(term)

    with _VOCAB_LOCK:
        _VOCAB_CACHE[key] = (mtime, terms)
    return terms


def as_initial_prompt(terms: list[str], max_chars: int = 220) -> str:
    return ", ".join(terms)[:max_chars]
