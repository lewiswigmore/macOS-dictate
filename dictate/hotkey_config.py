"""Parse hotkey combo strings and persist hotkey config back to settings.yaml.

Two responsibilities, kept in one small module to avoid YAML round-trip
complexity bleeding into the rest of the codebase:

1. `parse_combo("cmd+shift+space")` → (["cmd","shift"], "space"), with
   validation against the same KEY_MAP / MOD_MASKS the runtime tap uses.
2. `write_hotkey(path, mods, key)` → surgical text edit of settings.yaml that
   preserves comments and ordering. We only ever touch the `mods:` and `key:`
   lines, so a regex is safer (and simpler) than a YAML round-trip via
   ruamel.yaml.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from dictate.hotkey import KEY_MAP, MOD_MASKS

_MOD_ALIASES = {"command": "cmd", "alt": "option", "ctrl": "control"}
_CANONICAL_MODS = ("control", "option", "shift", "cmd")  # display order


class ComboParseError(ValueError):
    pass


def parse_combo(combo: str) -> tuple[list[str], str]:
    """Parse `mod+mod+key` into (mods, key). Case-insensitive. Raises ComboParseError."""
    raw_parts = [p.strip().lower() for p in (combo or "").split("+") if p.strip()]
    if len(raw_parts) < 2:
        raise ComboParseError("need at least one modifier and a key (e.g. cmd+space)")

    *mod_tokens, key = raw_parts
    mods: list[str] = []
    for tok in mod_tokens:
        canon = _MOD_ALIASES.get(tok, tok)
        if canon not in MOD_MASKS:
            raise ComboParseError(f"unknown modifier: {tok!r}")
        if canon not in mods:
            mods.append(canon)

    if key not in KEY_MAP:
        raise ComboParseError(f"unknown key: {key!r}")

    # Sort mods into a stable canonical order so equivalent combos round-trip.
    mods.sort(key=lambda m: _CANONICAL_MODS.index(m) if m in _CANONICAL_MODS else 99)
    return mods, key


def format_combo(mods: list[str], key: str) -> str:
    return "+".join([*mods, key])


_MOD_GLYPHS: dict[str, str] = {
    "control": "⌃",
    "option": "⌥",
    "shift": "⇧",
    "cmd": "⌘",
}

_KEY_GLYPHS: dict[str, str] = {
    "space": "Space",
    "return": "↩",
    "escape": "⎋",
    "tab": "⇥",
    "delete": "⌫",
}


def format_combo_glyph(mods: list[str], key: str) -> str:
    """Render a hotkey for menu display, e.g. ``["cmd"], "h"`` → ``⌘H``."""
    glyphs = "".join(_MOD_GLYPHS.get(m, m.upper()) for m in mods)
    key_glyph = _KEY_GLYPHS.get(key.lower(), key.upper())
    return f"{glyphs}{key_glyph}"


def write_hotkey(settings_path: Path, mods: list[str], key: str) -> None:
    """Update `mods:` and `key:` under the `hotkey:` block in settings.yaml.

    Comment-preserving: any trailing `# inline comment` on the line is kept.
    If the keys don't exist, the file is left untouched and we raise.
    """
    text = settings_path.read_text(encoding="utf-8")
    mods_repr = "[" + ", ".join(mods) + "]"

    # Pattern: (leading whitespace + key:)  (value, no newline, no #)  (optional # comment)
    mods_re = re.compile(r"^(\s*mods:\s*)([^\n#]*?)(\s*#.*)?$", re.M)
    key_re = re.compile(r"^(\s*key:\s*)([^\n#]*?)(\s*#.*)?$", re.M)

    def _replace(new_value: str):
        def _sub(m: re.Match) -> str:
            comment = m.group(3) or ""
            return f"{m.group(1)}{new_value}{comment}"

        return _sub

    new_text, n_mods = mods_re.subn(_replace(mods_repr), text, count=1)
    new_text, n_key = key_re.subn(_replace(key), new_text, count=1)
    if n_mods != 1 or n_key != 1:
        raise RuntimeError(
            f"could not locate hotkey lines in {settings_path} "
            f"(mods matched {n_mods}, key matched {n_key})"
        )
    # Atomic write: a SIGTERM or power loss mid-write_text could leave the
    # user's settings.yaml truncated. Stage to a tmp file in the same
    # directory (so os.replace is atomic) then swap.
    fd, tmp = tempfile.mkstemp(
        prefix=".settings.", suffix=".yaml.tmp", dir=str(settings_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, settings_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
