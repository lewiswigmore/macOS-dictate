from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Literal

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class Conflict:
    name: str
    severity: Severity
    detail: str
    suggestion: str


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    except Exception:  # noqa: BLE001
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _pgrep_exact(name: str) -> bool:
    return bool(_run(["pgrep", "-x", name]))


def macos_dictation_enabled() -> Conflict | None:
    output = _run(["defaults", "read", "com.apple.assistant.support", "Dictation Enabled"])
    if output == "1":
        return Conflict(
            name="macOS Dictation enabled",
            severity="warning",
            detail="Apple Dictation appears to be enabled and may compete for the microphone.",
            suggestion=(
                "Disable System Settings → Keyboard → Dictation so both apps do not fight "
                "for the mic when the hotkey is held."
            ),
        )
    return None


def voice_control_running() -> Conflict | None:
    state = _run(
        ["defaults", "read", "com.apple.universalaccessAuthWarning", "com.apple.SpeakableItems"]
    )
    found = state not in (None, "", "0")
    if not found:
        found = _pgrep_exact("VoiceControlAgent") or bool(_run(["pgrep", "-fl", "Voice Control"]))
    if found:
        return Conflict(
            name="Voice Control running",
            severity="warning",
            detail="macOS Voice Control appears to be running and may capture dictation audio.",
            suggestion="Turn off System Settings → Accessibility → Voice Control while using dictate.",
        )
    return None


def other_dictation_apps_running() -> list[Conflict]:
    conflicts: list[Conflict] = []
    for name in ("Superwhisper", "MacWhisper", "Whispering", "Aiko", "whisper-cpp"):
        if _pgrep_exact(name):
            conflicts.append(
                Conflict(
                    name=f"{name} running",
                    severity="warning",
                    detail=f"{name} is running and may compete for microphone access.",
                    suggestion=f"Quit {name} before using dictate if recording or hotkeys behave oddly.",
                )
            )
    return conflicts


def hotkey_likely_intercepted() -> Conflict | None:
    running = [
        name
        for name in ("Karabiner-Elements", "BetterTouchTool", "Keyboard Maestro")
        if _pgrep_exact(name)
    ]
    if running:
        names = ", ".join(running)
        return Conflict(
            name="Global hotkey tools running",
            severity="info",
            detail=f"Detected global hotkey tool(s): {names}.",
            suggestion=(
                "If the dictate hotkey does not fire, check these tools for a rule that "
                "intercepts the same shortcut first."
            ),
        )
    return None


def check_all() -> list[Conflict]:
    found: list[Conflict] = []
    for check in (macos_dictation_enabled, voice_control_running):
        try:
            conflict = check()
        except Exception:  # noqa: BLE001
            conflict = None
        if conflict is not None:
            found.append(conflict)
    try:
        found.extend(other_dictation_apps_running())
    except Exception:  # noqa: BLE001
        pass
    try:
        conflict = hotkey_likely_intercepted()
    except Exception:  # noqa: BLE001
        conflict = None
    if conflict is not None:
        found.append(conflict)
    return found
