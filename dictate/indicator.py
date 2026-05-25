"""Faint screen-edge flash on recording start / end.

A small translucent pill briefly appears just below the menu bar, tinted to
indicate state:

  • activated   → green
  • deactivated → neutral gray
  • cancelled   → red

The window is borderless, ignores mouse events, sits above normal windows but
below modal panels, and is fully click-through. Visible for ~500 ms with
fade-in / hold / fade-out so it doesn't distract.

Falls back to a silent no-op if AppKit is unavailable (test envs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .hud import _on_main  # reuse the main-thread marshaller
from .logging_setup import get_logger

if TYPE_CHECKING:
    from .config import Config

log = get_logger(__name__)

try:
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSPanel,
        NSScreen,
        NSView,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


# Mac status-bar height is 24 on retina (22 on legacy). Indicator sits just below it.
_PILL_WIDTH = 88
_PILL_HEIGHT = 10
_TOP_OFFSET = 30  # px below the screen top (i.e. just under the menu bar)
_CORNER_RADIUS = 5.0
_FINAL_ALPHA = 0.55
_FADE_IN_S = 0.10
_HOLD_S = 0.25
_FADE_OUT_S = 0.20

# RGB tints (0–1). Kept soft so the pill reads as "ambient", not "alert".
_COLORS: dict[str, tuple[float, float, float]] = {
    "activated": (0.30, 0.82, 0.45),  # soft green
    "deactivated": (0.65, 0.65, 0.65),  # neutral gray
    "cancelled": (0.92, 0.45, 0.45),  # soft red
}


class Indicator:
    """Single shared pill window; reused across flashes for zero alloc cost."""

    def __init__(self, config: Config) -> None:
        self._enabled: bool = bool(config.get("ui.indicator", True))
        self._panel: Any = None
        self._view: Any = None

    # ── public (thread-safe) ──────────────────────────────────────────────────

    def flash(self, state: str) -> None:
        if not self._enabled or not _AVAILABLE:
            return
        _on_main(lambda: self._flash_impl(state))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        if not on and self._panel is not None:
            _on_main(self._hide_impl)

    # ── main-thread internals ─────────────────────────────────────────────────

    def _flash_impl(self, state: str) -> None:
        rgb = _COLORS.get(state)
        if rgb is None:
            return
        try:
            self._ensure_panel()
            self._apply_tint(rgb)
            self._animate_show_then_hide()
        except Exception:  # noqa: BLE001 — UI should never propagate to caller
            log.debug("indicator flash failed", exc_info=True)

    def _ensure_panel(self) -> None:
        if self._panel is not None:
            return
        from AppKit import NSBorderlessWindowMask

        screen = NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.frame()
        x = frame.origin.x + (frame.size.width - _PILL_WIDTH) / 2.0
        # NSScreen origin is bottom-left → translate from top.
        y = frame.origin.y + frame.size.height - _TOP_OFFSET - _PILL_HEIGHT
        rect = ((x, y), (_PILL_WIDTH, _PILL_HEIGHT))

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSBorderlessWindowMask, NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setLevel_(25)  # above NSStatusWindowLevel, below modal panels
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )
        panel.setAlphaValue_(0.0)

        view = NSView.alloc().initWithFrame_(((0, 0), (_PILL_WIDTH, _PILL_HEIGHT)))
        view.setWantsLayer_(True)
        layer = view.layer()
        layer.setCornerRadius_(_CORNER_RADIUS)
        layer.setMasksToBounds_(True)
        panel.setContentView_(view)

        self._panel = panel
        self._view = view

    def _apply_tint(self, rgb: tuple[float, float, float]) -> None:
        from Quartz import CGColorCreateGenericRGB

        cg = CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], 1.0)
        self._view.layer().setBackgroundColor_(cg)

    def _animate_show_then_hide(self) -> None:
        from AppKit import NSAnimationContext
        from Foundation import NSTimer

        panel = self._panel
        panel.orderFrontRegardless()

        # Fade in.
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(_FADE_IN_S)
        panel.animator().setAlphaValue_(_FINAL_ALPHA)
        NSAnimationContext.endGrouping()

        def _fade_out(_: Any) -> None:
            try:
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(_FADE_OUT_S)
                panel.animator().setAlphaValue_(0.0)
                NSAnimationContext.endGrouping()
            except Exception:
                log.debug("indicator fade-out failed", exc_info=True)

        # Schedule the fade-out without blocking. The timer keeps a strong
        # reference to the callback for its lifetime; no manual retention.
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            _FADE_IN_S + _HOLD_S, False, _fade_out
        )

    def _hide_impl(self) -> None:
        if self._panel is not None:
            try:
                self._panel.setAlphaValue_(0.0)
                self._panel.orderOut_(None)
            except Exception:
                log.debug("indicator hide failed", exc_info=True)
