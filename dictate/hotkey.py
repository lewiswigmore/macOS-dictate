from __future__ import annotations

import enum
import threading
import time
from collections.abc import Callable

from .logging_setup import get_logger

log = get_logger(__name__)

try:
    import Quartz

    _QUARTZ_AVAILABLE = True
except ImportError:
    Quartz = None  # type: ignore[assignment]
    _QUARTZ_AVAILABLE = False

# macOS virtual keycodes (USB HID standard mapping used by CoreGraphics)
KEY_MAP: dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
    "space": 49,
    "escape": 53,
    "return": 36,
    "tab": 48,
    "delete": 51,
}

# kCGEventFlagMask* values (same in pyobjc and as raw ints)
MOD_MASKS: dict[str, int] = {
    "cmd": 0x100000,
    "command": 0x100000,
    "shift": 0x20000,
    "option": 0x80000,
    "alt": 0x80000,
    "control": 0x40000,
    "ctrl": 0x40000,
}

_ESC_KEYCODE: int = 53

# CGEventType values used for tap-disabled sentinels
_TAP_DISABLED_TIMEOUT: int = 0xFFFFFFFE
_TAP_DISABLED_USER_INPUT: int = 0xFFFFFFFD


class _State(enum.Enum):
    IDLE = "idle"
    PRESSED = "pressed"  # combo down, hold timer running
    HELD = "held"  # hold timer fired, still held
    TAP_PENDING = "tap_pending"  # released before hold, tap window timer running


class HotkeyState:
    """
    Pure state machine for the hold/tap/double-tap gesture.

    No Quartz dependency — events arrive as plain method calls.
    This separation lets tests exercise every branch without installing a
    real CGEventTap.

    State transitions:
        IDLE ──keyDown(combo,!repeat)──► PRESSED   (start hold_timer)
        PRESSED ──hold_timer fires──► HELD          (on_start if not recording)
        PRESSED ──keyUp──► TAP_PENDING              (start tap_window_timer)
        HELD ──keyUp or mod-drop──► IDLE            (on_stop)
        TAP_PENDING ──keyDown(combo)──► IDLE        (on_cancel: double-tap)
        TAP_PENDING ──tap_timer fires──► IDLE       (toggle: on_start or on_stop)
        any state ──ESC (recording)──► IDLE         (on_cancel)
    """

    def __init__(
        self,
        key_keycode: int,
        mod_mask: int,
        hold_threshold_ms: int,
        double_tap_window_ms: int,
        cancel_on_escape: bool,
        swallow_combo: bool,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
        mode: str = "auto",
        _time_fn: Callable[[], float] = time.monotonic,
        _timer_factory: Callable = threading.Timer,
    ) -> None:
        self._key_keycode = key_keycode
        self._mod_mask = mod_mask
        self._hold_ms = hold_threshold_ms
        self._tap_window_ms = double_tap_window_ms
        self._cancel_on_escape = cancel_on_escape
        self._swallow_combo = swallow_combo
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel
        # Input mode:
        #   "auto"   — hold→talk while held, tap→toggle (current behaviour)
        #   "hold"   — walkie-talkie; release ALWAYS stops, no toggle
        #   "toggle" — every press toggles, no hold-to-talk
        normalised = (mode or "auto").lower()
        self._mode: str = normalised if normalised in {"auto", "hold", "toggle"} else "auto"
        self._time_fn = _time_fn
        self._timer_factory = _timer_factory

        self._lock = threading.Lock()
        self._state = _State.IDLE
        self._is_recording: bool = False
        self._h_pressed: bool = False
        self._hold_timer: threading.Timer | None = None
        self._tap_timer: threading.Timer | None = None
        self._pause_override: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_pause_override(self, paused: bool) -> None:
        self._pause_override = paused

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_held(self) -> bool:
        """True if the user is actively holding the trigger (push-to-talk).

        Used by the auto-endpoint watcher to suppress silence-based cutoffs
        while the user is intentionally holding the key (e.g. thinking mid-utterance).
        """
        with self._lock:
            return self._state == _State.HELD or self._state == _State.PRESSED

    def handle_key_down(self, keycode: int, flags: int, auto_repeat: bool) -> bool:
        """Process a keyDown event.  Returns True if the event should be swallowed."""
        with self._lock:
            # ESC always cancels regardless of other logic
            if keycode == _ESC_KEYCODE and self._cancel_on_escape and self._is_recording:
                self._cancel_hold_timer()
                self._cancel_tap_timer()
                self._state = _State.IDLE
                self._h_pressed = False
                self._is_recording = False
                self._fire_callback(self._on_cancel, "on_cancel")
                return False  # never swallow Escape

            if not self._combo_matches(keycode, flags):
                return False

            swallow = self._swallow_combo and not self._pause_override

            if auto_repeat:
                return swallow

            if self._state == _State.IDLE:
                self._h_pressed = True

                # Pure toggle mode: skip the press-and-hold logic entirely.
                # Every press toggles, just like the tap-window timer firing.
                if self._mode == "toggle":
                    if not self._is_recording:
                        self._is_recording = True
                        self._fire_callback(self._on_start, "on_start")
                    else:
                        self._is_recording = False
                        self._fire_callback(self._on_stop, "on_stop")
                    return swallow

                t = self._timer_factory(self._hold_ms / 1000.0, self._on_hold_timer_fired)
                t.start()
                self._hold_timer = t
                self._state = _State.PRESSED

            elif self._state == _State.TAP_PENDING:
                # Second keyDown within the tap window → double-tap → cancel
                self._cancel_tap_timer()
                self._h_pressed = True
                self._state = _State.IDLE
                self._is_recording = False
                self._fire_callback(self._on_cancel, "on_cancel")

            # PRESSED or HELD: already handling, ignore extra down

            return swallow

    def handle_key_up(self, keycode: int, flags: int) -> bool:
        """Process a keyUp event.  Returns True if the event should be swallowed."""
        with self._lock:
            if keycode != self._key_keycode:
                return False

            self._h_pressed = False
            swallow = self._swallow_combo and not self._pause_override

            if self._state == _State.PRESSED:
                self._cancel_hold_timer()
                # Pure hold mode: release before hold-threshold = no-op (too short).
                # In auto mode we treat short presses as taps via the tap window.
                if self._mode == "hold":
                    self._state = _State.IDLE
                else:
                    t = self._timer_factory(self._tap_window_ms / 1000.0, self._on_tap_timer_fired)
                    t.start()
                    self._tap_timer = t
                    self._state = _State.TAP_PENDING

            elif self._state == _State.HELD:
                self._state = _State.IDLE
                self._is_recording = False
                self._fire_callback(self._on_stop, "on_stop")

            return swallow

    def handle_flags_changed(self, flags: int) -> bool:
        """Process a flagsChanged event.  Returns True if event should be swallowed."""
        with self._lock:
            mod_still_held = (flags & self._mod_mask) == self._mod_mask
            if mod_still_held or not self._h_pressed:
                return False

            # Modifier dropped while combo key is still physically held → treat as release
            self._h_pressed = False

            if self._state == _State.PRESSED:
                self._cancel_hold_timer()
                t = self._timer_factory(self._tap_window_ms / 1000.0, self._on_tap_timer_fired)
                t.start()
                self._tap_timer = t
                self._state = _State.TAP_PENDING

            elif self._state == _State.HELD:
                self._state = _State.IDLE
                self._is_recording = False
                self._fire_callback(self._on_stop, "on_stop")

            return False

    # ------------------------------------------------------------------
    # Timer callbacks (run on background threads)
    # ------------------------------------------------------------------

    def _on_hold_timer_fired(self) -> None:
        with self._lock:
            if self._state != _State.PRESSED:
                return
            self._hold_timer = None
            self._state = _State.HELD
            if not self._is_recording:
                self._is_recording = True
                self._fire_callback(self._on_start, "on_start")

    def _on_tap_timer_fired(self) -> None:
        with self._lock:
            if self._state != _State.TAP_PENDING:
                return
            self._tap_timer = None
            self._state = _State.IDLE
            if not self._is_recording:
                self._is_recording = True
                self._fire_callback(self._on_start, "on_start")
            else:
                self._is_recording = False
                self._fire_callback(self._on_stop, "on_stop")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _combo_matches(self, keycode: int, flags: int) -> bool:
        return keycode == self._key_keycode and (flags & self._mod_mask) == self._mod_mask

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _cancel_tap_timer(self) -> None:
        if self._tap_timer is not None:
            self._tap_timer.cancel()
            self._tap_timer = None

    def _fire_callback(self, cb: Callable[[], None], name: str) -> None:
        try:
            cb()
        except Exception:
            log.exception("Hotkey callback %s raised", name)


class HotkeyTap:
    """
    CGEventTap wrapper that translates low-level Quartz events into
    HotkeyState calls.  Requires Input Monitoring permission at runtime.
    """

    def __init__(
        self,
        config: object,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._config = config
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel

        self._state_machine = self._build_state_machine()
        self._tap: object = None
        self._run_loop_source: object = None

    def _build_state_machine(self) -> HotkeyState:
        hk: dict = self._config.get("hotkey", {})  # type: ignore[union-attr]

        mods: list[str] = hk.get("mods", ["cmd"])
        key: str = hk.get("key", "h")
        key_keycode = KEY_MAP.get(key.lower(), KEY_MAP["h"])
        mod_mask = 0
        for mod in mods:
            mod_mask |= MOD_MASKS.get(mod.lower(), 0)

        return HotkeyState(
            key_keycode=key_keycode,
            mod_mask=mod_mask,
            hold_threshold_ms=int(hk.get("hold_threshold_ms", 250)),
            double_tap_window_ms=int(hk.get("double_tap_window_ms", 400)),
            cancel_on_escape=bool(hk.get("cancel_on_escape", True)),
            swallow_combo=bool(hk.get("swallow_combo", True)),
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_cancel=self._on_cancel,
            mode=str(hk.get("mode", "auto")),
        )

    def reload(self) -> None:
        """Rebuild the state machine from the current config. Tap stays installed."""
        was_paused = self._state_machine._pause_override  # type: ignore[attr-defined]
        self._state_machine = self._build_state_machine()
        self._state_machine.set_pause_override(was_paused)
        log.info("hotkey reloaded from config")

    def set_pause_override(self, paused: bool) -> None:
        self._state_machine.set_pause_override(paused)

    def start(self) -> None:
        if not _QUARTZ_AVAILABLE:
            raise RuntimeError("Quartz (pyobjc) not available; cannot install CGEventTap.")
        self._install_tap()

    def stop(self) -> None:
        if not _QUARTZ_AVAILABLE or self._tap is None:
            return
        Quartz.CGEventTapEnable(self._tap, False)
        if self._run_loop_source is not None:
            Quartz.CFRunLoopRemoveSource(
                Quartz.CFRunLoopGetMain(),
                self._run_loop_source,
                Quartz.kCFRunLoopCommonModes,
            )
            self._run_loop_source = None
        self._tap = None

    # ------------------------------------------------------------------
    # Quartz plumbing
    # ------------------------------------------------------------------

    def _install_tap(self) -> None:
        mask = (
            (1 << Quartz.kCGEventKeyDown)
            | (1 << Quartz.kCGEventKeyUp)
            | (1 << Quartz.kCGEventFlagsChanged)
        )
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            self._quartz_callback,
            None,
        )
        if tap is None:
            raise RuntimeError(
                "Failed to create CGEventTap. "
                "Grant Input Monitoring permission in System Settings → Privacy."
            )
        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetMain(),
            run_loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(tap, True)
        self._tap = tap
        self._run_loop_source = run_loop_source

    def _quartz_callback(
        self, proxy: object, event_type: int, event: object, refcon: object
    ) -> object | None:
        try:
            if event_type in (_TAP_DISABLED_TIMEOUT, _TAP_DISABLED_USER_INPUT):
                log.warning("CGEventTap disabled (type=0x%X), re-enabling", event_type)
                Quartz.CGEventTapEnable(self._tap, True)
                return event

            keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
            flags = int(Quartz.CGEventGetFlags(event))
            swallow = False

            if event_type == Quartz.kCGEventKeyDown:
                auto_repeat = bool(
                    Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
                )
                swallow = self._state_machine.handle_key_down(keycode, flags, auto_repeat)

            elif event_type == Quartz.kCGEventKeyUp:
                swallow = self._state_machine.handle_key_up(keycode, flags)

            elif event_type == Quartz.kCGEventFlagsChanged:
                self._state_machine.handle_flags_changed(flags)

            return None if swallow else event

        except Exception:
            log.exception("Unhandled error in CGEventTap callback")
            return event
