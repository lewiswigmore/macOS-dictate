from __future__ import annotations

import sys
import time
from collections.abc import Callable

import rumps

from dictate.config import Config
from dictate.logging_setup import get_logger
from dictate.permissions import Permissions

log = get_logger(__name__)


class OnboardingWizard:
    """Sequential first-run wizard using rumps modal dialogs."""

    _PERM_META: list[tuple[str, str, Callable[[Permissions], bool]]] = [
        ("accessibility", "Accessibility", lambda p: p.check_accessibility()),
        ("microphone", "Microphone", lambda p: p.check_microphone()),
        ("input_monitoring", "Input Monitoring", lambda p: p.check_input_monitoring()),
    ]

    def __init__(
        self,
        config: Config,
        permissions: Permissions,
        backend_pinger: Callable[[str], bool],
    ) -> None:
        self._config = config
        self._permissions = permissions
        self._backend_pinger = backend_pinger

    def needs_wizard(self) -> bool:
        return not self._config.onboarded_marker.exists()

    def run(self) -> None:
        # Step 1 — Welcome.
        resp = rumps.alert(
            title="Welcome to dictate",
            message=(
                "dictate needs three macOS permissions to work:\n\n"
                "• Accessibility — to type and read the selection\n"
                "• Microphone — to record your voice\n"
                "• Input Monitoring — to listen for the hotkey\n\n"
                "The next screens will guide you through granting each one."
            ),
            ok="Continue",
            cancel="Quit",
        )
        if not resp:
            sys.exit(0)

        # Step 2 — Per-permission loop until all granted (or user quits).
        for pane_key, label, check_fn in self._PERM_META:
            while not check_fn(self._permissions):
                resp = rumps.alert(
                    title=f"{label} Permission Required",
                    message=(
                        f"dictate needs {label} access.\n\n"
                        "Click 'Open Settings' to grant it, then switch back here.\n"
                        "dictate will re-check automatically after a few seconds."
                    ),
                    ok="Open Settings",
                    cancel="Quit",
                )
                if not resp:
                    sys.exit(0)
                self._permissions.open_settings_pane(pane_key)
                # Give the user time to flip the toggle in Settings.
                time.sleep(3)

        # Step 3 — Backend reachability.
        backend_name = self._config.get("cleanup.backend", "ollama")
        if not self._backend_pinger(backend_name):
            resp = rumps.alert(
                title="Cleanup Backend Not Reachable",
                message=(
                    f"The backend '{backend_name}' didn't respond.\n\n"
                    "• ollama (default, local) — install from https://ollama.com,\n"
                    "  then run `ollama serve` and `ollama pull qwen2.5:3b-instruct`\n"
                    "• openrouter (optional cloud) — set OPENROUTER_API_KEY\n"
                    "  and change cleanup.backend in config/settings.yaml\n\n"
                    "You can also skip cleanup entirely — raw Whisper output will\n"
                    "be pasted as-is. Press Continue to finish setup anyway."
                ),
                ok="Continue",
                cancel="Quit",
            )
            if not resp:
                sys.exit(0)

        # Step 4 — Done.
        rumps.alert(
            title="You're all set!",
            message=(
                "Hotkey is Cmd+H.\n\n"
                "• Tap once to toggle recording on/off.\n"
                "• Hold to push-to-talk (releases when you lift the key).\n\n"
                "dictate is now running in your menu bar."
            ),
            ok="Start dictate",
        )

        # Step 5 — Persist the marker so we don't run again.
        marker = self._config.onboarded_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        log.info("onboarding complete")
