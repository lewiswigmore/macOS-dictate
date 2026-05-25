"""Dispatch dictate:// automation URLs.

The dictate:// scheme is declared in the plist template for future packaged .app
bundles. During source-tree development, launch URLs directly with:
``python3 -m dictate "dictate://toggle"``. Finder/open delivery only works once
dictate is packaged as a proper macOS app bundle that registers the scheme.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import unquote, urlparse

from dictate.logging_setup import get_logger

log = get_logger(__name__)


class AppController(Protocol):
    def start_recording(self) -> None: ...

    def stop_recording(self) -> None: ...

    def toggle_recording(self) -> None: ...

    def open_webui(self, entry_id: str | None = None) -> None: ...


def dispatch(url: str, controller: AppController) -> bool:
    """Returns True if URL was handled, False if unknown scheme/host."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "dictate":
            log.info("url scheme: %s -> ignored", url)
            return False

        action, tail = _action_and_tail(parsed.netloc, parsed.path)
        if action == "record" and tail is None:
            log.info("url scheme: %s -> start_recording", url)
            controller.start_recording()
            return True
        if action == "stop" and tail is None:
            log.info("url scheme: %s -> stop_recording", url)
            controller.stop_recording()
            return True
        if action == "toggle" and tail is None:
            log.info("url scheme: %s -> toggle_recording", url)
            controller.toggle_recording()
            return True
        if action == "history":
            entry_id = unquote(tail) if tail else None
            log.info("url scheme: %s -> open_webui", url)
            controller.open_webui(entry_id=entry_id)
            return True
        if action == "settings" and tail is None:
            log.info("url scheme: %s -> settings", url)
            log.info("url scheme settings requested; menubar settings are not implemented yet")
            return True

        log.info("url scheme: %s -> unknown", url)
        return False
    except Exception:
        log.exception("url scheme dispatch failed: %s", url)
        return False


def _action_and_tail(netloc: str, path: str) -> tuple[str, str | None]:
    parts = [unquote(part) for part in (netloc, *path.split("/")) if part]
    if not parts:
        return "", None
    action = parts[0]
    tail = "/".join(parts[1:]) or None
    return action, tail
