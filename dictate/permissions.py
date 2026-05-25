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

    def check_accessibility(self) -> bool:
        """Return True if the process has Accessibility (AX) trust."""
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions

            # Key is a CFString; PyObjC bridges str→CFString automatically.
            return bool(AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True}))
        except Exception as exc:
            log.warning("accessibility check failed: %s", exc)
            return False

    # ── microphone ────────────────────────────────────────────────────────────

    def check_microphone(self) -> bool:
        """Return True only if mic access is already Authorized."""
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
            if status == AVAuthorizationStatusNotDetermined:
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
