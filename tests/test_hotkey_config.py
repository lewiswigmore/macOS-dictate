from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from dictate.hotkey_config import (
    ComboParseError,
    format_combo,
    format_combo_glyph,
    parse_combo,
    write_hotkey,
)


class TestParseCombo:
    def test_simple(self):
        assert parse_combo("cmd+h") == (["cmd"], "h")

    def test_multiple_mods(self):
        assert parse_combo("cmd+shift+space") == (["shift", "cmd"], "space")

    def test_canonical_order(self):
        # Mods should be sorted into stable canonical order regardless of input.
        assert parse_combo("cmd+option+shift+a")[0] == ["option", "shift", "cmd"]

    def test_aliases(self):
        assert parse_combo("command+alt+f")[0] == ["option", "cmd"]
        assert parse_combo("ctrl+space") == (["control"], "space")

    def test_case_insensitive(self):
        assert parse_combo("CMD+H") == (["cmd"], "h")

    def test_dedupes_mods(self):
        assert parse_combo("cmd+cmd+a")[0] == ["cmd"]

    def test_rejects_unknown_mod(self):
        with pytest.raises(ComboParseError, match="modifier"):
            parse_combo("super+h")

    def test_rejects_unknown_key(self):
        with pytest.raises(ComboParseError, match="key"):
            parse_combo("cmd+ñ")

    def test_rejects_empty(self):
        with pytest.raises(ComboParseError):
            parse_combo("")

    def test_rejects_no_mod(self):
        with pytest.raises(ComboParseError):
            parse_combo("h")


def test_format_combo_roundtrip():
    mods, key = parse_combo("control+shift+cmd+a")
    assert format_combo(mods, key) == "control+shift+cmd+a"


class TestWriteHotkey:
    def _make_settings(self, tmp_path: Path) -> Path:
        p = tmp_path / "settings.yaml"
        p.write_text(
            textwrap.dedent(
                """\
                # top-of-file comment
                logging:
                  level: INFO

                hotkey:
                  mods: [cmd]                       # comment on mods
                  key: h
                  hold_threshold_ms: 250
                """
            )
        )
        return p

    def test_updates_in_place(self, tmp_path):
        p = self._make_settings(tmp_path)
        write_hotkey(p, ["shift", "cmd"], "space")
        text = p.read_text()
        assert "mods: [shift, cmd]" in text
        assert "key: space" in text
        assert "hold_threshold_ms: 250" in text  # untouched

    def test_preserves_comments(self, tmp_path):
        p = self._make_settings(tmp_path)
        write_hotkey(p, ["option"], "f1")
        text = p.read_text()
        assert "# top-of-file comment" in text
        assert "# comment on mods" in text

    def test_raises_when_keys_missing(self, tmp_path):
        p = tmp_path / "broken.yaml"
        p.write_text("logging:\n  level: INFO\n")
        with pytest.raises(RuntimeError, match="could not locate"):
            write_hotkey(p, ["cmd"], "h")


def test_format_combo_glyph_basic():
    assert format_combo_glyph(["cmd"], "h") == "⌘H"


def test_format_combo_glyph_multi_mod():
    assert format_combo_glyph(["control", "option", "shift", "cmd"], "a") == "⌃⌥⇧⌘A"


def test_format_combo_glyph_special_key():
    assert format_combo_glyph(["cmd"], "space") == "⌘Space"
    assert format_combo_glyph(["cmd"], "escape") == "⌘⎋"


class TestWriteHotkeyAtomicity:
    """Round-5 fix: write_hotkey must use tmp+rename so a crash mid-write
    cannot leave settings.yaml truncated."""

    def _settings(self, tmp_path: Path) -> Path:
        p = tmp_path / "settings.yaml"
        p.write_text("hotkey:\n  mods: [cmd]\n  key: h\n")
        return p

    def test_no_tmp_leftover_on_success(self, tmp_path):
        p = self._settings(tmp_path)
        write_hotkey(p, ["shift", "cmd"], "space")
        # tmp file pattern: .settings.*.yaml.tmp in the same dir.
        leftovers = list(tmp_path.glob(".settings.*.yaml.tmp"))
        assert leftovers == []
        # File is correctly updated.
        assert "key: space" in p.read_text()

    def test_tmp_cleaned_on_failure(self, tmp_path, monkeypatch):
        p = self._settings(tmp_path)

        import os as _os

        original_replace = _os.replace

        def boom(*args, **kwargs):
            raise OSError("simulated disk-full during rename")

        monkeypatch.setattr(_os, "replace", boom)

        with pytest.raises(OSError, match="simulated"):
            write_hotkey(p, ["cmd"], "h")

        # Original file untouched (still has previous contents).
        assert "key: h" in p.read_text()
        # No orphaned tmp files.
        leftovers = list(tmp_path.glob(".settings.*.yaml.tmp"))
        assert leftovers == [], f"orphan tmp files: {leftovers}"

        # Sanity: restore replace and confirm subsequent writes still work.
        monkeypatch.setattr(_os, "replace", original_replace)
        write_hotkey(p, ["option"], "f1")
        assert "key: f1" in p.read_text()
