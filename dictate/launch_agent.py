"""Install / remove the dictate LaunchAgent so it starts at login.

A LaunchAgent is the macOS-native way to keep dictate running across login,
sleep, and crashes. While dictate is running, its CGEventTap intercepts the
configured hotkey (default Cmd+H) before macOS can route it to the front app's
"Hide" command — making the suppression effectively permanent.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

LABEL = "com.dictate.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def is_installed() -> bool:
    return PLIST_PATH.exists()


def install(config: Config) -> Path:
    """Write the plist and load it via launchctl. Replaces any existing one."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_sh = config.root / "run.sh"
    log_path = Path(config.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    plist = {
        "Label": LABEL,
        # -lc gives us a login shell so PATH + ~/.zprofile are honoured, which
        # matters for whichever Python launchd picks up via /usr/bin/env in run.sh.
        "ProgramArguments": ["/bin/bash", "-lc", str(run_sh)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_path.with_name("launchd.stdout.log")),
        "StandardErrorPath": str(log_path.with_name("launchd.stderr.log")),
    }
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(plist, f)

    # bootout/bootstrap is the modern replacement for unload/load; fall back if missing.
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    target = f"gui/{uid}"
    subprocess.run(
        ["launchctl", "bootout", target, str(PLIST_PATH)], capture_output=True, check=False
    )
    subprocess.run(
        ["launchctl", "bootstrap", target, str(PLIST_PATH)], capture_output=True, check=False
    )
    log.info("LaunchAgent installed at %s", PLIST_PATH)
    return PLIST_PATH


def uninstall() -> bool:
    """Unload and remove the plist. Returns True if something was actually removed."""
    if not PLIST_PATH.exists():
        return False
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
        capture_output=True,
        check=False,
    )
    PLIST_PATH.unlink()
    log.info("LaunchAgent removed from %s", PLIST_PATH)
    return True
