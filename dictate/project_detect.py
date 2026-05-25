from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

# Cache: directory mtime → {lowercased_stem: Path}
_PROJECTS_CACHE: tuple[float, dict[str, Path]] | None = None
_PROJECTS_LOCK = Lock()


def _projects_dir(config: Config) -> Path:
    return config.root / "config" / "vocab" / "projects"


def available_projects(config: Config) -> dict[str, Path]:
    """Return {lowercased_stem: path} for all projects/*.txt files.

    Cached by directory mtime so repeated polls are cheap.
    """
    global _PROJECTS_CACHE
    pdir = _projects_dir(config)

    with _PROJECTS_LOCK:
        try:
            mtime = pdir.stat().st_mtime
        except OSError:
            return {}
        if _PROJECTS_CACHE is not None and _PROJECTS_CACHE[0] == mtime:
            return _PROJECTS_CACHE[1]

        out: dict[str, Path] = {}
        try:
            for p in pdir.glob("*.txt"):
                if p.is_file():
                    out[p.stem.lower()] = p
        except OSError:
            pass

        _PROJECTS_CACHE = (mtime, out)
        return out


_MAX_TITLE_LEN = 512


def detect_project(title: str | None, projects: dict[str, Path]) -> str | None:
    """Return the matching project stem found in *title*, or None.

    Matches on word boundary, case-insensitive. Prefers the longest matching
    project name so that, e.g. "dictate-mac" wins over "dictate" if both exist.
    Window titles longer than ``_MAX_TITLE_LEN`` chars are truncated to bound
    regex work — defensive against pathological titles from untrusted apps.
    """
    if not title or not projects:
        return None
    text = title[:_MAX_TITLE_LEN].lower()
    matches: list[str] = []
    for name in projects:
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            matches.append(name)
    if not matches:
        return None
    matches.sort(key=len, reverse=True)
    return matches[0]


def clear_cache() -> None:
    """For tests."""
    global _PROJECTS_CACHE
    with _PROJECTS_LOCK:
        _PROJECTS_CACHE = None
