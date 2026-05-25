from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extras = getattr(record, "extras", None)
        if extras:
            payload["extras"] = extras
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup(
    level: str = "INFO", json_logs: bool = True, file: str | None = None, rotate_days: int = 7
) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter: logging.Formatter
    if json_logs:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if file:
        path = Path(os.path.expanduser(file))
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(
            path, when="D", interval=1, backupCount=rotate_days, encoding="utf-8"
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
        # Tighten the active log + any already-rotated backups to owner-only.
        # Logs may contain redactions, command names, and other operational
        # detail we don't want any same-user process to read.
        _secure_log_files(path)
    _CONFIGURED = True


def _secure_log_files(path: Path) -> None:
    """Chmod the live log + rotated siblings to 0600 (best-effort)."""
    candidates = [path, *path.parent.glob(path.name + ".*")]
    for p in candidates:
        try:
            if p.exists():
                os.chmod(p, 0o600)
        except OSError:
            pass


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_metrics(logger: logging.Logger, event: str, **metrics: Any) -> None:
    logger.info(event, extra={"extras": metrics})
