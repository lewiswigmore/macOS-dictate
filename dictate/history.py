from __future__ import annotations

import errno
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dictate._filelock import exclusive_file_lock
from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)
_PARENT_READY: set[str] = set()
_HISTORY_FILE_MODE = 0o600
on_write_error: Callable[[dict], None] | None = None


def set_write_error_callback(callback: Callable[[dict], None] | None) -> None:
    global on_write_error
    on_write_error = callback


def _notify_write_error(event: dict) -> None:
    if on_write_error is None:
        return
    try:
        on_write_error(event)
    except Exception:
        log.debug("history write-error callback failed", exc_info=True)


def _ensure_secure_mode(path: Path) -> None:
    """Lock history file to owner-only (0600).

    History contains every raw + cleaned transcript and is persisted
    indefinitely. Even on a single-user Mac, other processes running as the
    same user (browser extensions, third-party tools) can read 0644 files in
    the home directory. Keep the perm tight; cheap idempotent call.

    Refuses to follow symlinks so a hostile config that points history.path
    at e.g. ~/.ssh/authorized_keys cannot trick us into changing the perms
    of a sensitive file.
    """
    try:
        if path.is_symlink():
            log.warning("refusing to chmod symlinked history path %s", path)
            return
        os.chmod(path, _HISTORY_FILE_MODE, follow_symlinks=False)
    except (OSError, NotImplementedError) as exc:
        log.warning("could not chmod history file %s: %s", path, exc)


def append(config: Config, entry: dict) -> None:
    if "ts" not in entry:
        entry = {**entry, "ts": datetime.now(UTC).isoformat()}
    path = Path(config.history_path)
    try:
        parent = str(path.parent)
        if parent not in _PARENT_READY:
            path.parent.mkdir(parents=True, exist_ok=True)
            _PARENT_READY.add(parent)
        with exclusive_file_lock(path):
            new_file = not path.exists()
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            if new_file or (path.stat().st_mode & 0o777) != _HISTORY_FILE_MODE:
                _ensure_secure_mode(path)
    except OSError as exc:
        event = {
            "type": "history_write_error",
            "path": str(path),
            "errno": exc.errno,
            "error": str(exc),
            "disk_full": exc.errno == errno.ENOSPC,
        }
        log.error(
            "history append failed for %s: %s",
            path,
            exc,
            extra={"extras": event},
        )
        _notify_write_error(event)


def last(config: Config, n: int = 1) -> list[dict]:
    path = Path(config.history_path)
    if not path.exists():
        return []
    with exclusive_file_lock(path):
        lines = path.read_text(encoding="utf-8").splitlines()
    tail = lines[-n:] if n <= len(lines) else lines
    result: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("malformed history line: %s", line[:80])
    return result


def reveal_last_in_finder(config: Config) -> None:
    path = Path(config.history_path)
    if not path.exists():
        return
    subprocess.run(["open", "-R", str(path)], check=False)


def purge_older_than(config: Config, days: int) -> int:
    """Stream-rewrite the JSONL file, dropping entries older than `days`.

    Returns the number of entries deleted. Holds the exclusive file lock for
    the entire rewrite so concurrent appends are serialised safely.
    """
    if days <= 0:
        return 0
    path = Path(config.history_path)
    if not path.exists():
        return 0

    cutoff = datetime.now(UTC).timestamp() - days * 86400
    kept: list[str] = []
    deleted = 0
    with exclusive_file_lock(path):
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                kept.append(raw)
                continue
            ts_text = row.get("ts")
            try:
                ts_value = (
                    datetime.fromisoformat(str(ts_text).replace("Z", "+00:00")).timestamp()
                    if ts_text
                    else None
                )
            except ValueError:
                ts_value = None
            if ts_value is not None and ts_value < cutoff:
                deleted += 1
                continue
            kept.append(raw)
        if deleted:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            os.replace(tmp, path)
            _ensure_secure_mode(path)
            log.info("auto-purged %d history entries older than %d days", deleted, days)
    return deleted
