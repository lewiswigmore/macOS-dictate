"""SF Symbols → NSImage helpers for the menu-bar UI and the HUD overlay.

All helpers degrade gracefully:
- If AppKit is unavailable (e.g. pytest without pyobjc) the helpers return None
  and `apply_*` setters return False; callers just leave the text label as-is.
- If a specific symbol name doesn't exist on the current macOS version,
  `symbol()` returns None for the same fallback path.

Requires macOS 11+ for `imageWithSystemSymbolName:accessibilityDescription:`.
"""

from __future__ import annotations

from typing import Any

try:
    from AppKit import (
        NSBezierPath,
        NSColor,
        NSImage,
        NSImageSymbolConfiguration,
    )
    from Foundation import NSMakeRect, NSMakeSize

    _AVAILABLE = True
except ImportError:  # pragma: no cover — only hit in test envs without pyobjc
    NSImage = None  # type: ignore[assignment]
    NSImageSymbolConfiguration = None  # type: ignore[assignment]
    NSBezierPath = None  # type: ignore[assignment]
    NSColor = None  # type: ignore[assignment]
    NSMakeRect = None  # type: ignore[assignment]
    NSMakeSize = None  # type: ignore[assignment]
    _AVAILABLE = False


CATALOG: dict[str, str] = {
    "app": "mic.fill",
    "state.idle": "mic",
    "state.recording": "record.circle.fill",
    "state.cleaning": "wand.and.stars",
    "state.pasting": "arrow.down.doc.fill",
    "health.ok": "checkmark.circle.fill",
    "health.bad": "xmark.circle.fill",
}


# Dictate brand mark — scattered rounded squares (viewBox 60×60). Shared with
# the WebUI SVG. Drawn as a template NSImage so macOS tints to the menu bar.
_BRAND_SHAPES: tuple[tuple[float, float, float, float], ...] = (
    (3,  27, 6,  6),
    (13, 16, 8,  8),
    (13, 38, 6,  6),
    (25,  6, 10, 10),
    (25, 26, 8,  8),
    (25, 44, 6,  6),
    (39, 18, 12, 12),
    (39, 42, 8,  8),
    (52,  8, 6,  6),
    (52, 32, 6,  6),
    (52, 50, 6,  6),  # accent (cyan in UI; tinted in menubar)
)
_BRAND_VIEWBOX_W = 60.0
_BRAND_VIEWBOX_H = 60.0


def brand_template_image(point_height: float = 18.0) -> Any | None:
    """Render the Dictate scattered mark as a menubar-ready template NSImage.

    Returns None if AppKit isn't available. The returned image is marked as a
    template so macOS applies the correct tint for the active appearance.
    """
    if not _AVAILABLE:
        return None
    try:
        scale = point_height / _BRAND_VIEWBOX_H
        width = _BRAND_VIEWBOX_W * scale
        size = NSMakeSize(width, point_height)
        image = NSImage.alloc().initWithSize_(size)
        image.lockFocus()
        try:
            NSColor.blackColor().setFill()
            for vx, vy, vw, vh in _BRAND_SHAPES:
                x = vx * scale
                # Flip Y: SVG origin is top-left, Cocoa is bottom-left.
                y = (_BRAND_VIEWBOX_H - vy - vh) * scale
                w = vw * scale
                h = vh * scale
                radius = max(1.0, 1.5 * scale)
                rect = NSMakeRect(x, y, w, h)
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    rect, radius, radius
                )
                path.fill()
        finally:
            image.unlockFocus()
        image.setTemplate_(True)
        return image
    except Exception:  # noqa: BLE001
        return None


def symbol(key_or_name: str, point_size: float = 14.0) -> Any | None:
    """Return an NSImage for a catalog key (preferred) or a raw SF Symbol name."""
    if not _AVAILABLE:
        return None
    name = CATALOG.get(key_or_name, key_or_name)
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, name)
    if img is None:
        return None
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(point_size, 0)
    return img.imageWithSymbolConfiguration_(config)


def apply_to_menu_item(item: Any, key_or_name: str, point_size: float = 14.0) -> bool:
    """Set an SF Symbol image on a rumps MenuItem. Returns True on success."""
    img = symbol(key_or_name, point_size)
    if img is None:
        return False
    try:
        item._menuitem.setImage_(img)
        return True
    except Exception:  # noqa: BLE001
        return False


def write_brand_template_png(path: str, point_height: float = 18.0) -> bool:
    """Render the brand mark to a template PNG file. Returns True on success.

    Use this when the consumer (e.g. rumps) needs a file path rather than an
    in-memory NSImage. The PNG is suitable for use as a macOS menubar icon
    when paired with ``template=True``.
    """
    if not _AVAILABLE:
        return False
    img = brand_template_image(point_height=point_height)
    if img is None:
        return False
    try:
        from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep
        tiff = img.TIFFRepresentation()
        rep = NSBitmapImageRep.imageRepWithData_(tiff)
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
        return bool(png.writeToFile_atomically_(path, True))
    except Exception:  # noqa: BLE001
        return False


def apply_to_app(app: Any, key_or_name: str, point_size: float = 16.0) -> bool:
    """Set the menu-bar status icon. Clears the text title on success.

    For ``key_or_name == "app"`` this uses the Dictate brand waveform mark.
    Anything else falls back to the SF Symbol catalog.
    """
    img: Any | None
    if key_or_name == "app":
        img = brand_template_image(point_height=point_size + 2.0)
        if img is None:
            img = symbol(key_or_name, point_size)
    else:
        img = symbol(key_or_name, point_size)
    if img is None:
        return False
    try:
        if not getattr(img, "isTemplate", lambda: False)():
            img.setTemplate_(True)
        button = app._nsapp.nsstatusitem.button()
        button.setImage_(img)
        button.setTitle_("")
        return True
    except Exception:  # noqa: BLE001
        return False
