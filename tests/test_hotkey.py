from __future__ import annotations

"""
Tests for the HotkeyState state machine.

All Quartz interaction is bypassed — HotkeyState is imported directly and fed
synthetic events.  A FakeTimer replaces threading.Timer so we can fire timers
manually without sleeping.
"""

from collections.abc import Callable
from unittest.mock import MagicMock

# HotkeyState lives in dictate.hotkey.  The module wraps the Quartz import
# in a try/except so this import succeeds even without pyobjc installed.
from dictate.hotkey import HotkeyState

# ------------------------------------------------------------------
# Keyboard constants (matching KEY_MAP / MOD_MASKS in hotkey.py)
# ------------------------------------------------------------------
H_KEYCODE = 4
ESC_KEYCODE = 53
CMD_FLAG = 0x100000
NO_FLAGS = 0


# ------------------------------------------------------------------
# FakeTimer infrastructure
# ------------------------------------------------------------------


class _FakeTimer:
    """Drop-in replacement for threading.Timer that fires only when told."""

    def __init__(self, delay: float, fn: Callable[[], None]) -> None:
        self.delay = delay
        self.fn = fn
        self._cancelled = False

    def start(self) -> None:
        pass  # intentionally a no-op

    def cancel(self) -> None:
        self._cancelled = True

    def fire(self) -> None:
        if not self._cancelled:
            self.fn()


class _TimerFactory:
    """Records every FakeTimer created so tests can fire them on demand."""

    def __init__(self) -> None:
        self._timers: list[_FakeTimer] = []

    def __call__(self, delay: float, fn: Callable[[], None]) -> _FakeTimer:
        t = _FakeTimer(delay, fn)
        self._timers.append(t)
        return t

    def fire_latest(self) -> None:
        """Fire the most recently created (non-cancelled) timer."""
        for t in reversed(self._timers):
            if not t._cancelled:
                t.fire()
                return

    def fire_all(self) -> None:
        for t in self._timers:
            t.fire()

    def clear(self) -> None:
        self._timers.clear()


# ------------------------------------------------------------------
# Fixture helpers
# ------------------------------------------------------------------


def _make_state(
    *,
    swallow_combo: bool = True,
    cancel_on_escape: bool = True,
    hold_threshold_ms: int = 250,
    double_tap_window_ms: int = 400,
    mode: str = "auto",
) -> tuple[HotkeyState, MagicMock, MagicMock, MagicMock, _TimerFactory]:
    on_start = MagicMock()
    on_stop = MagicMock()
    on_cancel = MagicMock()
    timers = _TimerFactory()

    state = HotkeyState(
        key_keycode=H_KEYCODE,
        mod_mask=CMD_FLAG,
        hold_threshold_ms=hold_threshold_ms,
        double_tap_window_ms=double_tap_window_ms,
        cancel_on_escape=cancel_on_escape,
        swallow_combo=swallow_combo,
        on_start=on_start,
        on_stop=on_stop,
        on_cancel=on_cancel,
        mode=mode,
        _timer_factory=timers,
    )
    return state, on_start, on_stop, on_cancel, timers


# ------------------------------------------------------------------
# Test: HOLD gesture  (cmd+h held > hold_threshold → on_start; release → on_stop)
# ------------------------------------------------------------------


class TestHold:
    def test_hold_fires_on_start_then_on_stop(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        on_start.assert_not_called()

        # Simulate hold timer expiry
        timers.fire_latest()
        on_start.assert_called_once()
        assert state.is_recording is True

        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        on_stop.assert_called_once()
        assert state.is_recording is False

    def test_hold_not_triggered_on_auto_repeat(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, True)  # auto-repeat
        timers.fire_all()
        on_start.assert_not_called()

    def test_hold_on_start_called_only_once(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        timers.fire_latest()  # transitions to HELD, calls on_start
        # Firing a stale timer again must not re-call on_start
        timers.fire_latest()
        assert on_start.call_count == 1


# ------------------------------------------------------------------
# Test: TAP gesture  (single tap = toggle continuous)
# ------------------------------------------------------------------


class TestTap:
    def test_tap_starts_recording(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        on_start.assert_not_called()  # not yet: waiting for tap window

        timers.fire_latest()  # tap window expires → toggle → on_start
        on_start.assert_called_once()
        assert state.is_recording is True

    def test_tap_stops_recording_when_already_recording(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        # First tap: start recording
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        timers.fire_latest()
        assert state.is_recording is True

        # Second tap: stop recording
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        timers.fire_latest()
        on_stop.assert_called_once()
        assert state.is_recording is False


# ------------------------------------------------------------------
# Test: DOUBLE-TAP  (two taps within window while recording → on_cancel)
# ------------------------------------------------------------------


class TestDoubleTap:
    def test_double_tap_while_recording_calls_cancel(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        # Start recording via single tap
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        timers.fire_latest()
        assert state.is_recording is True

        # First tap of double-tap sequence
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        # Tap window timer is now running — do NOT fire it

        # Second tap keyDown within the window → cancel
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        on_cancel.assert_called_once()
        on_stop.assert_not_called()
        assert state.is_recording is False

    def test_single_tap_does_not_cancel(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        timers.fire_latest()  # single tap window expires
        on_cancel.assert_not_called()

    def test_double_tap_when_not_recording_still_cancels(self) -> None:
        """Double-tap always calls on_cancel regardless of recording state."""
        state, on_start, on_stop, on_cancel, timers = _make_state()

        # First tap (tap window opens)
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        # Second tap keyDown before window expires
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        on_cancel.assert_called_once()


# ------------------------------------------------------------------
# Test: ESC while recording → on_cancel
# ------------------------------------------------------------------


class TestEscapeCancel:
    def test_esc_while_recording_calls_cancel(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        # Start recording
        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        timers.fire_latest()
        assert state.is_recording is True

        state.handle_key_down(ESC_KEYCODE, NO_FLAGS, False)
        on_cancel.assert_called_once()
        assert state.is_recording is False

    def test_esc_when_not_recording_does_nothing(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(ESC_KEYCODE, NO_FLAGS, False)
        on_cancel.assert_not_called()

    def test_esc_not_swallowed(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        timers.fire_latest()
        result = state.handle_key_down(ESC_KEYCODE, NO_FLAGS, False)
        assert result is False


# ------------------------------------------------------------------
# Test: swallow_combo + pause_override
# ------------------------------------------------------------------


class TestSwallow:
    def test_swallow_combo_true_swallows_event(self) -> None:
        state, *_ = _make_state(swallow_combo=True)
        result = state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        assert result is True

    def test_swallow_combo_false_passes_through(self) -> None:
        state, *_ = _make_state(swallow_combo=False)
        result = state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        assert result is False

    def test_pause_override_disables_swallow(self) -> None:
        """swallow_combo=True but pause_override=True → event not swallowed."""
        state, *_ = _make_state(swallow_combo=True)
        state.set_pause_override(True)
        result = state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        assert result is False

    def test_pause_override_false_restores_swallow(self) -> None:
        state, *_ = _make_state(swallow_combo=True)
        state.set_pause_override(True)
        state.set_pause_override(False)
        result = state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        assert result is True

    def test_non_combo_key_never_swallowed(self) -> None:
        state, *_ = _make_state(swallow_combo=True)
        result = state.handle_key_down(0, CMD_FLAG, False)  # 'a', not 'h'
        assert result is False


# ------------------------------------------------------------------
# Test: modifier-drop while key held (treat as release)
# ------------------------------------------------------------------


class TestFlagsChanged:
    def test_mod_drop_during_hold_triggers_stop(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        timers.fire_latest()  # → HELD, on_start called
        assert state.is_recording is True

        # Cmd released while H still physically down
        state.handle_flags_changed(NO_FLAGS)
        on_stop.assert_called_once()
        assert state.is_recording is False

    def test_mod_drop_during_pressed_transitions_to_tap_pending(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state()

        state.handle_key_down(H_KEYCODE, CMD_FLAG, False)
        # Cmd drops before hold timer fires
        state.handle_flags_changed(NO_FLAGS)
        # Tap window timer should be running now; fire it → on_start
        timers.fire_latest()
        on_start.assert_called_once()


# ------------------------------------------------------------------
# Test: hotkey.mode = "toggle" — every press toggles, no hold-to-talk
# ------------------------------------------------------------------


class TestToggleMode:
    def test_press_starts_recording_immediately(self) -> None:
        state, on_start, on_stop, on_cancel, _ = _make_state(mode="toggle")
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        assert on_start.call_count == 1
        assert state.is_recording

    def test_second_press_stops_recording(self) -> None:
        state, on_start, on_stop, on_cancel, _ = _make_state(mode="toggle")
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        assert on_start.call_count == 1
        assert on_stop.call_count == 1
        assert not state.is_recording

    def test_holding_does_not_keep_recording_on_release(self) -> None:
        # In toggle mode the key-up should not stop recording; only another press does.
        state, on_start, on_stop, on_cancel, _ = _make_state(mode="toggle")
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        assert state.is_recording
        assert on_stop.call_count == 0


# ------------------------------------------------------------------
# Test: hotkey.mode = "hold" — release ALWAYS stops; no toggle behaviour
# ------------------------------------------------------------------


class TestHoldOnlyMode:
    def test_hold_then_release_stops(self) -> None:
        state, on_start, on_stop, on_cancel, timers = _make_state(mode="hold")
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        # Fire the hold timer
        timers.fire_latest()
        assert on_start.call_count == 1
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        assert on_stop.call_count == 1
        assert not state.is_recording

    def test_short_press_does_not_toggle(self) -> None:
        # Tap (release before hold timer fires) should be a no-op in hold mode,
        # NOT a toggle that starts recording.
        state, on_start, on_stop, on_cancel, _ = _make_state(mode="hold")
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        assert on_start.call_count == 0
        assert on_stop.call_count == 0
        assert not state.is_recording


class TestPlainKeyPassthrough:
    """Plain trigger-key presses (no modifier) must not be swallowed.

    Regression: handle_key_up previously matched only on keycode, so typing
    a plain "h" character had its keyup swallowed, leaving the OS thinking
    H was stuck held.
    """

    def test_plain_key_down_not_swallowed(self) -> None:
        state, on_start, on_stop, on_cancel, _ = _make_state()
        swallow = state.handle_key_down(H_KEYCODE, NO_FLAGS, auto_repeat=False)
        assert swallow is False
        assert on_start.call_count == 0

    def test_plain_key_up_not_swallowed(self) -> None:
        state, on_start, on_stop, on_cancel, _ = _make_state()
        # No prior combo keydown was accepted, so the keyup must pass through
        # even though the keycode matches the trigger key.
        swallow = state.handle_key_up(H_KEYCODE, NO_FLAGS)
        assert swallow is False
        assert on_stop.call_count == 0
        assert on_cancel.call_count == 0

    def test_plain_key_up_after_real_combo_still_passes_through(self) -> None:
        # Full combo press/release, then a plain "h" tap immediately after.
        state, on_start, on_stop, on_cancel, timers = _make_state()
        state.handle_key_down(H_KEYCODE, CMD_FLAG, auto_repeat=False)
        state.handle_key_up(H_KEYCODE, CMD_FLAG)
        timers.fire_latest()  # tap window fires → toggle on
        assert state.is_recording
        on_start.reset_mock()

        # Plain "h" typed while recording must not be swallowed and must not
        # affect the recording state.
        assert state.handle_key_down(H_KEYCODE, NO_FLAGS, auto_repeat=False) is False
        assert state.handle_key_up(H_KEYCODE, NO_FLAGS) is False
        assert state.is_recording
        assert on_stop.call_count == 0
