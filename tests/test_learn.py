from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dictate.config import Config
from dictate.learn import LearnWatcher


@pytest.fixture
def cfg(tmp_path):
    return Config(
        root=tmp_path,
        settings={
            "history": {"path": str(tmp_path / "history.jsonl")},
            "learn": {"enabled": True, "watch_window_seconds": 0.5, "poll_interval_seconds": 0.05},
        },
    )


@pytest.fixture
def watcher(cfg):
    return LearnWatcher(cfg, history_appender=MagicMock(), context=MagicMock())


def _write_history(cfg: Config, entries: list[dict]) -> None:
    p = Path(cfg.history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


class TestRecentCorrections:
    def test_empty_when_no_history(self, watcher):
        assert watcher.recent_corrections("default", 4) == []

    def test_zero_n_returns_empty(self, watcher, cfg):
        _write_history(
            cfg, [{"type": "correction", "preset": "default", "raw": "a", "correction": "A"}]
        )
        assert watcher.recent_corrections("default", 0) == []

    def test_filters_by_type_and_preset(self, watcher, cfg):
        _write_history(
            cfg,
            [
                {"type": "utterance", "preset": "default", "raw": "x", "correction": "X"},  # skip
                {"type": "correction", "preset": "code", "raw": "a", "correction": "A"},  # skip
                {"type": "correction", "preset": "default", "raw": "b", "correction": "B"},
                {"type": "correction", "preset": "default", "raw": "c", "correction": "C"},
            ],
        )
        got = watcher.recent_corrections("default", 4)
        assert got == [("b", "B"), ("c", "C")]

    def test_returns_only_last_n(self, watcher, cfg):
        _write_history(
            cfg,
            [
                {"type": "correction", "preset": "default", "raw": f"r{i}", "correction": f"C{i}"}
                for i in range(10)
            ],
        )
        got = watcher.recent_corrections("default", 3)
        assert got == [("r7", "C7"), ("r8", "C8"), ("r9", "C9")]

    def test_cache_invalidates_on_mtime_change(self, watcher, cfg):
        _write_history(
            cfg, [{"type": "correction", "preset": "default", "raw": "a", "correction": "A"}]
        )
        assert watcher.recent_corrections("default", 5) == [("a", "A")]

        # Mutate file with a guaranteed-different mtime.
        time.sleep(0.01)
        _write_history(
            cfg,
            [
                {"type": "correction", "preset": "default", "raw": "a", "correction": "A"},
                {"type": "correction", "preset": "default", "raw": "b", "correction": "B"},
            ],
        )
        new_mtime = os.path.getmtime(cfg.history_path) + 1
        os.utime(cfg.history_path, (new_mtime, new_mtime))

        assert watcher.recent_corrections("default", 5) == [("a", "A"), ("b", "B")]

    def test_cache_hits_when_mtime_unchanged(self, watcher, cfg, monkeypatch):
        _write_history(
            cfg, [{"type": "correction", "preset": "default", "raw": "a", "correction": "A"}]
        )
        watcher.recent_corrections("default", 5)  # populate
        rebuild_calls = []
        real_rebuild = watcher._rebuild_cache
        monkeypatch.setattr(
            watcher,
            "_rebuild_cache",
            lambda *a, **k: rebuild_calls.append(1) or real_rebuild(*a, **k),
        )
        for _ in range(5):
            watcher.recent_corrections("default", 5)
        assert rebuild_calls == []  # no rebuilds on unchanged file

    def test_malformed_lines_skipped(self, watcher, cfg):
        p = Path(cfg.history_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            '{"type": "correction", "preset": "default", "raw": "a", "correction": "A"}\n'
            "not json at all\n"
            "\n"
            '{"type": "correction", "preset": "default", "raw": "b", "correction": "B"}\n'
        )
        got = watcher.recent_corrections("default", 5)
        assert got == [("a", "A"), ("b", "B")]


class TestArm:
    def test_skips_when_learn_disabled(self, cfg):
        cfg.settings["learn"]["enabled"] = False
        ctx = MagicMock()
        w = LearnWatcher(cfg, history_appender=MagicMock(), context=ctx)
        w.arm("hello", "Hello.")
        # Should bail before touching context.
        ctx.frontmost.assert_not_called()

    def test_skips_when_raw_equals_cleaned(self, cfg):
        ctx = MagicMock()
        w = LearnWatcher(cfg, history_appender=MagicMock(), context=ctx)
        w.arm("hello world", "  hello world  ")  # whitespace-only diff
        ctx.frontmost.assert_not_called()

    def test_starts_watcher_thread_otherwise(self, cfg):
        ctx = MagicMock()
        ctx.frontmost.return_value = {"name": "TestApp", "bundle_id": "x"}
        ctx.preset_for.return_value = "default"
        ctx.read_focused_value.return_value = None
        w = LearnWatcher(cfg, history_appender=MagicMock(), context=ctx)
        w.arm("raw text", "cleaned text")
        # Watcher should have called frontmost() once when arming.
        assert ctx.frontmost.call_count == 1
