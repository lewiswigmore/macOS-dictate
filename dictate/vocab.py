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

# Tracks which (max_chars, terms) truncations we've already warned about, so
# a vocab set that overflows the cap logs once rather than on every
# dictation — as_initial_prompt runs once per utterance.
_TRUNCATION_WARNED: set[tuple[int, tuple[str, ...]]] = set()
_TRUNCATION_WARNED_LOCK = Lock()


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
    """Join vocab terms into a Whisper initial_prompt, truncated to max_chars.

    Truncation drops whole terms rather than cutting one in half, and logs a
    warning naming what was dropped — previously this silently discarded
    anything past the cap with no signal to the user.

    This runs once per dictation, so the warning is rate-limited to once per
    unique (max_chars, terms) truncation rather than firing on every
    utterance and drowning out other log lines.
    """
    kept: list[str] = []
    total = 0
    dropped: list[str] = []
    for i, term in enumerate(terms):
        added = len(term) + (2 if kept else 0)  # ", " separator
        if total + added > max_chars:
            dropped = terms[i:]
            break
        kept.append(term)
        total += added

    if dropped:
        key = (max_chars, tuple(terms))
        with _TRUNCATION_WARNED_LOCK:
            already_warned = key in _TRUNCATION_WARNED
            _TRUNCATION_WARNED.add(key)
        if not already_warned:
            log.warning(
                "vocab prompt truncated at %d chars: dropped %d/%d term(s): %s",
                max_chars,
                len(dropped),
                len(terms),
                ", ".join(dropped),
            )

    return ", ".join(kept)
