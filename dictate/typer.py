from __future__ import annotations

import ctypes
import ctypes.util
import threading
import time
from typing import Any

from dictate.config import load_config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

_V_KEYCODE = 9
_RETURN_KEYCODE = 36
_DELETE_KEYCODE = 51
_TYPE_CHUNK_SIZE = 20
_RESTORE_DELAY_S = 0.2
_DEFAULT_PRE_PASTE_DELAY_S = 0.05
_DEFAULT_PASTE_WAIT_MS = 50
_SECURE_INPUT_WARNING = "secure input active — refusing to paste (likely password field focused)"


def _secure_input_active() -> bool:
    try:
        carbon_path = ctypes.util.find_library("Carbon")
        if not carbon_path:
            return False
        carbon = ctypes.CDLL(carbon_path)
        carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        return bool(carbon.IsSecureEventInputEnabled())
    except Exception:
        return False


def _cfg_get(config: Any | None, dotted: str, default: Any) -> Any:
    if config is None:
        return default
    get = getattr(config, "get", None)
    if not callable(get):
        return default
    return get(dotted, default)


class Typer:
    def __init__(
        self,
        pre_paste_delay: float = _DEFAULT_PRE_PASTE_DELAY_S,
        force_type: bool = False,
        config: Any | None = None,
    ) -> None:
        if config is None:
            try:
                config = load_config()
            except Exception:
                log.warning("failed to load typer config; using safe defaults", exc_info=True)
        self._pre_paste_delay = pre_paste_delay
        self._force_type = force_type
        self._refuse_on_secure_input = bool(_cfg_get(config, "typer.refuse_on_secure_input", True))
        self._paste_wait_s = (
            max(0, int(_cfg_get(config, "typer.paste_wait_ms", _DEFAULT_PASTE_WAIT_MS))) / 1000
        )

    def type_text(self, text: str, force_type: bool = False) -> bool:
        return self.paste(text, force_type=force_type)

    def paste(self, text: str, force_type: bool = False) -> bool:
        if self._force_type or force_type:
            return self.type_chars(text)
        try:
            import Quartz  # type: ignore[import]
            from AppKit import NSPasteboard, NSPasteboardTypeString  # type: ignore[import]
        except Exception:
            log.warning("paste() imports failed, falling back to type_chars", exc_info=True)
            return self.type_chars(text)

        pb = NSPasteboard.generalPasteboard()
        previous = pb.stringForType_(NSPasteboardTypeString)
        restore_deferred = False
        clipboard_dirty = False
        try:
            pb.clearContents()
            pb.setString_forType_(text, NSPasteboardTypeString)
            clipboard_dirty = True

            # Secure Event Input is global on macOS; if a password field or sudo prompt
            # enabled it, synthetic Cmd+V can still paste into that sensitive field.
            if self._refuse_on_secure_input and _secure_input_active():
                log.warning(_SECURE_INPUT_WARNING)
                self._restore_clipboard(pb, NSPasteboardTypeString, previous)
                self._schedule_clipboard_restore(pb, NSPasteboardTypeString, previous)
                restore_deferred = True
                return False

            if self._pre_paste_delay > 0:
                time.sleep(self._pre_paste_delay)

            self._post_cmd_v(Quartz)

            # Some apps and clipboard managers observe the paste asynchronously; this
            # configurable wait gives Cmd+V a short window before restoration is queued.
            if self._paste_wait_s > 0:
                time.sleep(self._paste_wait_s)

            self._schedule_clipboard_restore(pb, NSPasteboardTypeString, previous)
            restore_deferred = True
            return True
        except Exception:
            log.warning("paste() failed, falling back to type_chars", exc_info=True)
            if clipboard_dirty:
                self._restore_clipboard(pb, NSPasteboardTypeString, previous)
                clipboard_dirty = False
            return self.type_chars(text)
        finally:
            if clipboard_dirty and not restore_deferred:
                self._restore_clipboard(pb, NSPasteboardTypeString, previous)

    def _post_cmd_v(self, quartz: Any) -> None:
        src = quartz.CGEventSourceCreate(quartz.kCGEventSourceStateHIDSystemState)
        for keydown in (True, False):
            ev = quartz.CGEventCreateKeyboardEvent(src, _V_KEYCODE, keydown)
            quartz.CGEventSetFlags(ev, quartz.kCGEventFlagMaskCommand)
            quartz.CGEventPost(quartz.kCGHIDEventTap, ev)

    def _schedule_clipboard_restore(
        self, pb: Any, pasteboard_type: Any, previous: str | None
    ) -> None:
        timer = threading.Timer(
            _RESTORE_DELAY_S,
            lambda: self._restore_clipboard(pb, pasteboard_type, previous),
        )
        timer.daemon = True
        timer.start()

    def _restore_clipboard(self, pb: Any, pasteboard_type: Any, previous: str | None) -> None:
        try:
            pb.clearContents()
            if previous is not None:
                pb.setString_forType_(previous, pasteboard_type)
        except Exception:
            log.warning("failed to restore clipboard", exc_info=True)

    def type_chars(self, text: str) -> bool:
        # Sends text as raw Unicode key events in chunks — works even when Accessibility
        # paste is rejected. Each chunk posted as keyDown + keyUp pair.
        try:
            import Quartz  # type: ignore[import]

            src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            for i in range(0, len(text), _TYPE_CHUNK_SIZE):
                chunk = text[i : i + _TYPE_CHUNK_SIZE]
                for keydown in (True, False):
                    ev = Quartz.CGEventCreateKeyboardEvent(src, 0, keydown)
                    Quartz.CGEventKeyboardSetUnicodeString(ev, len(chunk), chunk)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
                time.sleep(0.005)
            return True
        except Exception:
            log.error("type_chars() failed", exc_info=True)
            return False

    def insert_newline(self) -> bool:
        try:
            import Quartz  # type: ignore[import]

            src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            for keydown in (True, False):
                ev = Quartz.CGEventCreateKeyboardEvent(src, _RETURN_KEYCODE, keydown)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            return True
        except Exception:
            log.error("insert_newline() failed", exc_info=True)
            return False

    def backspace(self, n: int) -> bool:
        if n <= 0:
            return True
        try:
            import Quartz  # type: ignore[import]

            src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            for _ in range(n):
                for keydown in (True, False):
                    ev = Quartz.CGEventCreateKeyboardEvent(src, _DELETE_KEYCODE, keydown)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            return True
        except Exception:
            log.error("backspace() failed", exc_info=True)
            return False
