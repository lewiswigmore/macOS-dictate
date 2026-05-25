from __future__ import annotations

import threading
from typing import Any

from dictate.config import Config
from dictate.icons import symbol as sf_symbol
from dictate.logging_setup import get_logger

log = get_logger(__name__)

_PANEL_HEIGHT = 64
_VU_HEIGHT = 4
_LABEL_MARGIN = 12
_DOT_SIZE = 8
_ICON_SIZE = 16
_ICON_GAP = 6

_STATE_LABELS: dict[str, str] = {
    "idle": "Idle",
    "recording": "Recording",
    "cleaning": "Cleaning",
    "pasting": "Pasting",
}

_STATE_SYMBOLS: dict[str, str] = {
    "idle": "state.idle",
    "recording": "state.recording",
    "cleaning": "state.cleaning",
    "pasting": "state.pasting",
}

# ── main-thread marshalling ───────────────────────────────────────────────────

_invoker_cls: Any = None
_invoker_lock = threading.Lock()


def _get_invoker_cls() -> Any:
    global _invoker_cls
    if _invoker_cls is not None:
        return _invoker_cls
    with _invoker_lock:
        if _invoker_cls is not None:
            return _invoker_cls
        from Foundation import NSObject

        class _Invoker(NSObject):
            # Python-level slot; underscore prefix keeps PyObjC from bridging it.
            _fn: Any = None

            def fire_(self, _: Any) -> None:  # ObjC selector: fire:
                if self._fn is not None:
                    self._fn()

        _invoker_cls = _Invoker
        return _invoker_cls


def _on_main(fn: Any) -> None:
    """Marshal fn() to the main CFRunLoop thread — fire-and-forget."""
    try:
        from Foundation import NSThread
    except ImportError:
        fn()
        return
    if NSThread.isMainThread():
        fn()
        return
    inv = _get_invoker_cls().alloc().init()
    inv._fn = fn
    # waitUntilDone=False keeps background threads from stalling.
    inv.performSelectorOnMainThread_withObject_waitUntilDone_("fire:", None, False)


# ── HUD ───────────────────────────────────────────────────────────────────────


class HUD:
    """Click-through borderless NSPanel status overlay."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._streaming: bool = bool(config.get("hud.streaming", True))
        self._width: int = int(config.get("hud.width", 480))
        self._panel: Any = None
        self._label: Any = None
        self._icon_view: Any = None
        self._vu_track: Any = None
        self._vu_bar: Any = None
        self._dot: Any = None
        self._built = False

    # ── public API (thread-safe) ──────────────────────────────────────────────

    def show_recording(self) -> None:
        _on_main(lambda: self._show_state_impl("recording"))

    def show_partial(self, text: str) -> None:
        if not self._streaming:
            return
        _on_main(lambda: self._set_label_impl(text))

    def show_state(self, state: str) -> None:
        _on_main(lambda: self._show_state_impl(state))

    def set_vu(self, level: float) -> None:
        _on_main(lambda: self._set_vu_impl(level))

    def set_backend_status(self, name: str, ok: bool) -> None:
        _on_main(lambda: self._set_dot_impl(ok))

    def hide(self) -> None:
        _on_main(self._hide_impl)

    # ── main-thread implementations ───────────────────────────────────────────

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._built = True
        self._build_panel()

    def _build_panel(self) -> None:
        from AppKit import (
            NSBackingStoreBuffered,
            NSColor,
            NSFont,
            NSLineBreakByTruncatingMiddle,
            NSPanel,
            NSScreen,
            NSStatusWindowLevel,
            NSTextField,
            NSView,
            NSWindowStyleMaskBorderless,
        )

        w = self._width
        h = _PANEL_HEIGHT
        sf = NSScreen.mainScreen().frame()
        x = sf.origin.x + (sf.size.width - w) / 2
        y = sf.origin.y + 24  # small gap above dock / bottom edge

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (w, h)),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setIgnoresMouseEvents_(True)
        panel.setOpaque_(False)
        panel.setHasShadow_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.65))
        # Show on all Spaces / full-screen apps.
        panel.setCollectionBehavior_(1)  # NSWindowCollectionBehaviorCanJoinAllSpaces

        cv = panel.contentView()
        cv.setWantsLayer_(True)
        layer = cv.layer()
        layer.setCornerRadius_(10.0)
        layer.setMasksToBounds_(True)

        # VU track — dim strip across the full bottom edge.
        vu_track = NSView.alloc().initWithFrame_(((0, 0), (w, _VU_HEIGHT)))
        vu_track.setWantsLayer_(True)
        vu_track.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.15).CGColor()
        )
        cv.addSubview_(vu_track)

        # VU bar — active green fill, starts at zero width.
        vu_bar = NSView.alloc().initWithFrame_(((0, 0), (0, _VU_HEIGHT)))
        vu_bar.setWantsLayer_(True)
        vu_bar.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.25, 0.88, 0.42, 1.0).CGColor()
        )
        vu_track.addSubview_(vu_bar)

        # Partial-transcript label — single line, truncated in the middle.
        # State icon sits to the left of the label (SF Symbol, tinted white).
        label_y = _VU_HEIGHT + (_PANEL_HEIGHT - _VU_HEIGHT - 22) // 2
        icon_y = _VU_HEIGHT + (_PANEL_HEIGHT - _VU_HEIGHT - _ICON_SIZE) // 2
        label_x = _LABEL_MARGIN + _ICON_SIZE + _ICON_GAP
        label_w = w - label_x - _LABEL_MARGIN - _DOT_SIZE - 8

        from AppKit import NSImageView

        icon_view = NSImageView.alloc().initWithFrame_(
            ((_LABEL_MARGIN, icon_y), (_ICON_SIZE, _ICON_SIZE))
        )
        icon_view.setImageScaling_(0)  # NSImageScaleProportionallyDown
        try:
            icon_view.setContentTintColor_(NSColor.whiteColor())
        except AttributeError:
            pass  # older macOS — image will render in its default colour
        cv.addSubview_(icon_view)

        label = NSTextField.alloc().initWithFrame_(((label_x, label_y), (label_w, 22)))
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(13.0))
        label.cell().setLineBreakMode_(NSLineBreakByTruncatingMiddle)
        label.setStringValue_("")
        cv.addSubview_(label)

        # Backend status dot — small circle, right-aligned.
        dot_x = w - _LABEL_MARGIN - _DOT_SIZE
        dot_y = _VU_HEIGHT + (_PANEL_HEIGHT - _VU_HEIGHT - _DOT_SIZE) // 2
        dot = NSView.alloc().initWithFrame_(((dot_x, dot_y), (_DOT_SIZE, _DOT_SIZE)))
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(_DOT_SIZE / 2)
        dot.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.3).CGColor())
        cv.addSubview_(dot)

        self._panel = panel
        self._label = label
        self._icon_view = icon_view
        self._vu_track = vu_track
        self._vu_bar = vu_bar
        self._dot = dot

    def _show_state_impl(self, state: str) -> None:
        self._ensure_built()
        self._label.setStringValue_(_STATE_LABELS.get(state, state.capitalize()))
        img = sf_symbol(_STATE_SYMBOLS.get(state, "state.idle"))
        if img is not None:
            self._icon_view.setImage_(img)
        if not self._panel.isVisible():
            self._panel.orderFront_(None)

    def _set_label_impl(self, text: str) -> None:
        self._ensure_built()
        self._label.setStringValue_(text)
        if not self._panel.isVisible():
            self._panel.orderFront_(None)

    def _set_vu_impl(self, level: float) -> None:
        self._ensure_built()
        level = max(0.0, min(1.0, level))
        track_w = self._vu_track.frame().size.width
        self._vu_bar.setFrame_(((0, 0), (track_w * level, _VU_HEIGHT)))

    def _set_dot_impl(self, ok: bool) -> None:
        self._ensure_built()
        from AppKit import NSColor

        color = (
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.25, 0.88, 0.42, 1.0)
            if ok
            else NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.22, 0.22, 1.0)
        )
        self._dot.layer().setBackgroundColor_(color.CGColor())

    def _hide_impl(self) -> None:
        if self._panel is not None and self._panel.isVisible():
            self._panel.orderOut_(None)
