from __future__ import annotations

from dictate.logging_setup import get_logger

log = get_logger(__name__)

_PREF_URLS: dict[str, str] = {
    "accessibility": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    ),
    "microphone": ("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"),
    "input_monitoring": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
    ),
}

# IOHIDCheckAccess constants (IOKit/HIDDriverKit, macOS 10.15+)
_kIOHIDRequestTypeListenEvent: int = 1
_kIOHIDAccessTypeGranted: int = 0


class Permissions:
    """Checks and requests macOS permissions required by dictate."""

    # ── accessibility ─────────────────────────────────────────────────────────

    def check_accessibility(self, *, prompt: bool = True) -> bool:
        """Return True if the process has Accessibility (AX) trust.

        ``prompt=False`` performs a silent check — required for polled status
        readouts, since the prompting variant re-opens the System Settings
        nag every time it is called.
        """
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions

            # Key is a CFString; PyObjC bridges str→CFString automatically.
            return bool(AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": prompt}))
        except Exception as exc:
            log.warning("accessibility check failed: %s", exc)
            return False

    # ── microphone ────────────────────────────────────────────────────────────

    def check_microphone(self, *, prompt: bool = True) -> bool:
        """Return True only if mic access is already Authorized.

        ``prompt=False`` performs a silent check and never triggers the
        system permission dialog — required for polled status readouts,
        since requesting access on every poll would prompt the user
        repeatedly for a permission that is merely being displayed, not
        actually needed yet.
        """
        try:
            from AVFoundation import (
                AVAuthorizationStatusAuthorized,
                AVAuthorizationStatusNotDetermined,
                AVCaptureDevice,
                AVMediaTypeAudio,
            )

            status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
            if status == AVAuthorizationStatusAuthorized:
                return True
            if prompt and status == AVAuthorizationStatusNotDetermined:
                # Triggers the system prompt; result comes asynchronously.
                AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVMediaTypeAudio, lambda _granted: None
                )
            return False
        except Exception as exc:
            log.warning("microphone check failed: %s", exc)
            return False

    # ── input monitoring ──────────────────────────────────────────────────────

    def check_input_monitoring(self) -> bool:
        """Return True if the process has Input Monitoring permission.

        Primary path: IOHIDCheckAccess via ctypes (macOS 10.15+).
        Fallback: attempt a listen-only CGEventTap — NULL return means denied.
        """
        try:
            return self._check_iohid()
        except Exception:
            pass
        try:
            return self._check_cgeventtap()
        except Exception as exc:
            log.warning("input_monitoring check failed: %s", exc)
            return False

    @staticmethod
    def _check_iohid() -> bool:
        import ctypes

        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit")
        iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        result = iokit.IOHIDCheckAccess(_kIOHIDRequestTypeListenEvent)
        return int(result) == _kIOHIDAccessTypeGranted

    @staticmethod
    def _check_cgeventtap() -> bool:
        import Quartz

        def _passthrough(proxy, type_, event, data):  # noqa: ANN001
            return event

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            1 << Quartz.kCGEventKeyDown,
            _passthrough,
            None,
        )
        if tap is None:
            return False
        Quartz.CFRelease(tap)
        return True

    # ── settings deep-links ───────────────────────────────────────────────────

    def open_settings_pane(self, pane: str) -> None:
        """Open the relevant Privacy pane in System Settings / Preferences."""
        url_str = _PREF_URLS.get(pane)
        if not url_str:
            log.warning("unknown settings pane: %s", pane)
            return
        try:
            from AppKit import NSWorkspace
            from Foundation import NSURL

            url = NSURL.URLWithString_(url_str)
            NSWorkspace.sharedWorkspace().openURL_(url)
        except Exception as exc:
            log.warning("open_settings_pane(%s) failed: %s", pane, exc)

    # ── convenience ───────────────────────────────────────────────────────────

    def all_granted(self) -> dict[str, bool]:
        return {
            "accessibility": self.check_accessibility(),
            "microphone": self.check_microphone(),
            "input_monitoring": self.check_input_monitoring(),
        }


# Consequence of each grant being missing, surfaced in the WebUI.
_PERMISSION_IMPACT: dict[str, str] = {
    "accessibility": "Required to paste transcribed text and read the selection.",
    "microphone": "Required to record audio. Dictation cannot capture anything.",
    "input_monitoring": "Required for the hotkey. Without it the shortcut does nothing.",
}


def check_all(*, prompt: bool = False) -> dict[str, bool]:
    """Silent permission snapshot, keyed by permission name.

    Safe to poll: defaults to ``prompt=False`` so no System Settings dialog
    and no microphone permission prompt is raised. Used by the WebUI status
    panel.
    """
    perms = Permissions()
    return {
        "accessibility": perms.check_accessibility(prompt=prompt),
        "microphone": perms.check_microphone(prompt=prompt),
        "input_monitoring": perms.check_input_monitoring(),
    }


def impact(key: str) -> str:
    """Human-readable consequence of `key` not being granted."""
    return _PERMISSION_IMPACT.get(key, "")


def settings_url(key: str) -> str:
    """Deep link to the System Settings pane governing `key`."""
    return _PREF_URLS.get(key, "")
