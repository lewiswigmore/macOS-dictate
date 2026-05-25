from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dictate.logging_setup import get_logger

log = get_logger(__name__)


def _state_dir() -> Path:
    base = Path(os.environ.get("DICTATE_STATE_DIR") or
                Path.home() / "Library" / "Application Support" / "dictate")
    base.mkdir(parents=True, exist_ok=True)
    return base


def pid_file() -> Path:
    return _state_dir() / "dictate.pid"


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid() -> int | None:
    pf = pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    if not _is_alive(pid):
        try:
            pf.unlink()
        except OSError:
            pass
        return None
    return pid


def write_pid() -> None:
    pid_file().write_text(f"{os.getpid()}\n")


def clear_pid() -> None:
    pf = pid_file()
    try:
        if pf.exists() and pf.read_text().strip() == str(os.getpid()):
            pf.unlink()
    except OSError:
        pass


def _launcher_argv() -> list[str]:
    return [sys.executable, "-m", "dictate"]


def cmd_status() -> int:
    pid = read_pid()
    if pid is None:
        print("dictate: not running")
        return 1
    print(f"dictate: running (pid {pid})")
    print(f"  pidfile: {pid_file()}")
    return 0


def cmd_start(*, foreground: bool = False) -> int:
    existing = read_pid()
    if existing is not None:
        print(f"dictate: already running (pid {existing})")
        return 1
    if foreground:
        from dictate.app import run_app
        write_pid()
        try:
            run_app()
        finally:
            clear_pid()
        return 0

    log_path = _state_dir() / "dictate.log"
    with open(log_path, "ab") as logf:
        proc = subprocess.Popen(
            _launcher_argv() + ["--_internal-foreground"],
            stdout=logf,
            stderr=logf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    for _ in range(50):
        time.sleep(0.1)
        pid = read_pid()
        if pid == proc.pid:
            print(f"dictate: started (pid {pid})")
            print(f"  logs: {log_path}")
            return 0
    print(f"dictate: launched pid {proc.pid} but did not see pidfile; check {log_path}")
    return 1


def cmd_stop(*, timeout: float = 8.0) -> int:
    pid = read_pid()
    if pid is None:
        print("dictate: not running")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("dictate: not running")
        try:
            pid_file().unlink()
        except OSError:
            pass
        return 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_alive(pid):
            print(f"dictate: stopped (pid {pid})")
            try:
                pid_file().unlink()
            except OSError:
                pass
            return 0
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        pid_file().unlink()
    except OSError:
        pass
    print(f"dictate: force-killed (pid {pid})")
    return 0


def cmd_restart() -> int:
    if read_pid() is not None:
        cmd_stop()
    return cmd_start()
