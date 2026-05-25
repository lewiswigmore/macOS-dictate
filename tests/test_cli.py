from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(REPO_ROOT.parent)
    env["DICTATE_DOCTOR_SKIP_SLOW_CHECKS"] = "1"
    return env


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dictate", *args],
        cwd=REPO_ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_version_flag_prints_versions():
    result = _run("--version")
    assert result.returncode == 0
    assert "dictate " in result.stdout
    assert "Python " in result.stdout
    assert "macOS " in result.stdout


def test_dry_run_loads_config_without_starting_app():
    result = _run("--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dictate dry-run: OK" in result.stdout


def test_doctor_subcommand_prints_report():
    result = _run("doctor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dictate doctor" in result.stdout
    assert "System" in result.stdout
    assert "Permissions" in result.stdout
    assert "Backends" in result.stdout
