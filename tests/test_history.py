from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest

from dictate.config import Config
from dictate.history import (
    _PARENT_READY,
    append,
    last,
    reveal_last_in_finder,
    set_write_error_callback,
)


@pytest.fixture
def cfg(tmp_path: Path):
    return Config(root=tmp_path, settings={"history": {"path": str(tmp_path / "h.jsonl")}})


@pytest.fixture(autouse=True)
def _clear_parent_cache():
    _PARENT_READY.clear()
    yield
    _PARENT_READY.clear()


def test_append_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "h.jsonl"
    cfg = Config(root=tmp_path, settings={"history": {"path": str(nested)}})
    append(cfg, {"type": "x", "raw": "hello"})
    assert nested.exists()
    line = json.loads(nested.read_text().strip())
    assert line["raw"] == "hello"
    assert "ts" in line  # auto-added


def test_append_preserves_provided_ts(cfg):
    append(cfg, {"type": "x", "ts": "2024-01-01T00:00:00+00:00"})
    line = json.loads(Path(cfg.history_path).read_text().strip())
    assert line["ts"] == "2024-01-01T00:00:00+00:00"


def test_append_then_last(cfg):
    for i in range(5):
        append(cfg, {"type": "x", "n": i})
    items = last(cfg, n=3)
    assert [e["n"] for e in items] == [2, 3, 4]


def test_last_returns_empty_when_no_file(cfg):
    assert last(cfg) == []


def test_last_skips_malformed_lines(cfg):
    Path(cfg.history_path).write_text('{"type": "ok", "n": 1}\nNOT JSON\n{"type": "ok", "n": 2}\n')
    items = last(cfg, n=10)
    assert [e["n"] for e in items] == [1, 2]


def test_mkdir_cache_avoids_second_mkdir_call(cfg, monkeypatch):
    calls = []
    real_mkdir = Path.mkdir

    def spy_mkdir(self, *a, **kw):
        calls.append(str(self))
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    append(cfg, {"type": "x"})
    append(cfg, {"type": "y"})
    append(cfg, {"type": "z"})
    # mkdir should only be invoked on the parent the first time
    parent = str(Path(cfg.history_path).parent)
    assert calls.count(parent) == 1


def test_reveal_last_in_finder_is_a_noop_when_missing(cfg):
    # Just must not raise.
    reveal_last_in_finder(cfg)


def test_append_disk_full_logs_and_posts_event(cfg, monkeypatch, caplog):
    events = []
    real_open = Path.open
    history_path = Path(cfg.history_path)

    def fake_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        if self == history_path and "a" in mode:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open)
    set_write_error_callback(events.append)
    try:
        append(cfg, {"type": "x", "raw": "hello"})
    finally:
        set_write_error_callback(None)

    assert events
    assert events[0]["type"] == "history_write_error"
    assert events[0]["errno"] == errno.ENOSPC
    assert events[0]["disk_full"] is True
    assert "history append failed" in caplog.text


class TestHistoryFilePermissions:
    """Round-3 fix (HIGH PII): history.jsonl must be 0600 — readable only by
    the owner. Same-user processes (browser extensions, indexers) can read
    0644 files in ~/, and history contains every raw + cleaned transcript."""

    def test_new_file_is_0600(self, cfg):
        append(cfg, {"type": "utterance", "raw": "secret"})
        mode = Path(cfg.history_path).stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    def test_repairs_existing_loose_perms(self, cfg):
        # Pre-create with world-readable perms (simulating an old install).
        path = Path(cfg.history_path)
        path.write_text('{"type": "old"}\n')
        import os as _os

        _os.chmod(path, 0o644)
        assert path.stat().st_mode & 0o777 == 0o644
        # Next append must tighten perms.
        append(cfg, {"type": "new"})
        assert path.stat().st_mode & 0o777 == 0o600


from datetime import UTC, datetime, timedelta

from dictate.history import purge_older_than


class TestPurgeOlderThan:
    def test_purge_removes_old_entries(self, cfg):
        now = datetime.now(UTC)
        path = Path(cfg.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {"type": "utterance", "raw": "old1", "ts": (now - timedelta(days=40)).isoformat()},
            {"type": "utterance", "raw": "old2", "ts": (now - timedelta(days=31)).isoformat()},
            {"type": "utterance", "raw": "fresh", "ts": (now - timedelta(days=2)).isoformat()},
            {"type": "utterance", "raw": "today", "ts": now.isoformat()},
        ]
        import json as _json
        path.write_text("\n".join(_json.dumps(line) for line in lines) + "\n")
        import os as _os
        _os.chmod(path, 0o600)
        deleted = purge_older_than(cfg, days=30)
        assert deleted == 2
        remaining = path.read_text().strip().splitlines()
        assert len(remaining) == 2
        assert all("old" not in line for line in remaining)
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_purge_noop_when_days_zero(self, cfg):
        deleted = purge_older_than(cfg, days=0)
        assert deleted == 0

    def test_purge_handles_missing_file(self, cfg):
        deleted = purge_older_than(cfg, days=7)
        assert deleted == 0

    def test_purge_keeps_malformed_lines(self, cfg):
        path = Path(cfg.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        path.write_text(
            '{"raw": "old", "ts": "' + old_ts + '"}\nnot-json-keep\n{"raw": "no_ts"}\n'
        )
        import os as _os
        _os.chmod(path, 0o600)
        deleted = purge_older_than(cfg, days=30)
        assert deleted == 1
        lines = path.read_text().strip().splitlines()
        assert "not-json-keep" in lines
        assert any('"no_ts"' in line for line in lines)


class TestPurgeTmpFileMode:
    """Round-4 fix (security): the rewritten history must be born 0o600 so
    no same-user process can read it during the brief window between write
    and rename. Path.write_text honours umask (typically 0o022 on macOS)
    and would have left ``history.jsonl.tmp`` world-readable. Using
    tempfile.NamedTemporaryFile fixes that — verify the mode the moment
    the tmp file is created."""

    def test_purge_tmp_file_is_0o600(self, cfg, monkeypatch):
        import stat as _stat
        import tempfile as _tempfile

        path = Path(cfg.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        path.write_text('{"raw": "old", "ts": "' + old_ts + '"}\n')
        import os as _os
        _os.chmod(path, 0o600)

        observed_modes: list[int] = []
        real_ntf = _tempfile.NamedTemporaryFile

        def spy(*args, **kwargs):
            handle = real_ntf(*args, **kwargs)
            observed_modes.append(_stat.S_IMODE(_os.stat(handle.name).st_mode))
            return handle

        monkeypatch.setattr("dictate.history.tempfile.NamedTemporaryFile", spy)
        deleted = purge_older_than(cfg, days=30)
        assert deleted == 1
        assert observed_modes, "expected NamedTemporaryFile to be called"
        assert all(m == 0o600 for m in observed_modes), (
            f"expected 0o600 from the moment of tmp creation, got "
            f"{[oct(m) for m in observed_modes]}"
        )
        # Final file is still 0o600 after the replace.
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_no_tmp_sibling_left_behind(self, cfg):
        path = Path(cfg.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        path.write_text('{"raw": "old", "ts": "' + old_ts + '"}\n')
        import os as _os
        _os.chmod(path, 0o600)
        purge_older_than(cfg, days=30)
        # ``history.jsonl.lock`` is the file-lock sibling; anything else
        # named ``*.tmp`` would be the leftover we're guarding against.
        leftovers = [
            p.name
            for p in path.parent.iterdir()
            if p.name != path.name and p.name.endswith(".tmp")
        ]
        assert leftovers == [], f"expected no tmp leftovers, got {leftovers}"
