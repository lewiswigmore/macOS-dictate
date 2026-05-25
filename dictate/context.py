from __future__ import annotations

import re
from pathlib import Path

from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)

_IDE_BUNDLES = frozenset(
    {
        "com.microsoft.VSCode",
        "com.microsoft.VSCodeInsiders",
        "com.visualstudio.code.oss",
        "com.todesktop.230313mzl4w4u92",  # Cursor
        "com.apple.dt.Xcode",
        "com.jetbrains.intellij",
        "com.jetbrains.pycharm",
        "com.jetbrains.goland",
        "com.jetbrains.WebStorm",
        "com.jetbrains.CLion",
        "com.sublimetext.4",
    }
)

_EMPTY_FRONTMOST: dict = {
    "bundle_id": None,
    "name": None,
    "pid": None,
    "project_path": None,
    "title": None,
    "project": None,
}


def _parse_project_from_title(title: str, bundle_id: str, search_roots: list[Path]) -> str | None:
    # Split on em-dash (VS Code, Xcode) or en-dash (JetBrains)
    parts = re.split(r" [—–] ", title)
    candidate: str | None = None

    if any(x in bundle_id for x in ("VSCode", "visualstudio", "todesktop")):
        # "filename — folder — Visual Studio Code"  →  parts[-2] is the folder
        candidate = parts[-2].strip() if len(parts) >= 2 else parts[0].strip()
    elif "Xcode" in bundle_id:
        # "ProjectName — scheme — …"  →  first segment is the project
        candidate = parts[0].strip()
    elif "jetbrains" in bundle_id:
        # "ProjectName – IDE Name"  →  first segment
        candidate = parts[0].strip()
    else:
        candidate = parts[0].strip() if parts else None

    if not candidate:
        return None

    if candidate.startswith("/"):
        p = Path(candidate)
        return str(p) if p.exists() else None

    for root in search_roots:
        p = root / candidate
        if p.is_dir():
            return str(p)

    return None


class ContextProbe:
    def __init__(self, config: Config) -> None:
        self._config = config

    def frontmost(self) -> dict:
        try:
            from AppKit import NSWorkspace  # type: ignore[import]

            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return dict(_EMPTY_FRONTMOST)
            bundle_id = app.bundleIdentifier()
            name = app.localizedName()
            pid = int(app.processIdentifier())
            title = self._window_title(pid)
            project_path = (
                _parse_project_from_title(title, bundle_id, self._config.project_search_roots)
                if (title and bundle_id in _IDE_BUNDLES)
                else None
            )
            project = self._detect_project_name(title, project_path)
            return {
                "bundle_id": bundle_id,
                "name": name,
                "pid": pid,
                "project_path": project_path,
                "title": title,
                "project": project,
            }
        except Exception:
            log.debug("frontmost() failed", exc_info=True)
            return dict(_EMPTY_FRONTMOST)

    def _window_title(self, pid: int) -> str | None:
        try:
            from ApplicationServices import (  # type: ignore[import]  # noqa: PLC0415
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
                kAXFocusedWindowAttribute,
                kAXMainWindowAttribute,
                kAXTitleAttribute,
            )

            app_elem = AXUIElementCreateApplication(pid)
            err, window = AXUIElementCopyAttributeValue(app_elem, kAXMainWindowAttribute, None)
            if err != 0 or window is None:
                err, window = AXUIElementCopyAttributeValue(
                    app_elem, kAXFocusedWindowAttribute, None
                )
            if err != 0 or window is None:
                return None
            err, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
            if err != 0 or not title:
                return None
            return str(title)
        except Exception:
            return None

    def _detect_project_name(self, title: str | None, project_path: str | None) -> str | None:
        from dictate.project_detect import available_projects, detect_project

        projects = available_projects(self._config)
        if not projects:
            return None
        # IDE path → derive name from folder basename and confirm a vocab file exists.
        if project_path:
            base = Path(project_path).name.lower()
            if base in projects:
                return base
        # Fallback to title-based detection (works for terminals, browsers, chat apps).
        return detect_project(title, projects)

    def _infer_project_path(self, bundle_id: str, pid: int) -> str | None:
        title = self._window_title(pid)
        if not title:
            return None
        return _parse_project_from_title(title, bundle_id, self._config.project_search_roots)

    def preset_for(self, frontmost_info: dict) -> str:
        return self._config.preset_for_bundle(frontmost_info.get("bundle_id"))

    def read_selection(self, max_chars: int = 2048, frontmost: dict | None = None) -> str | None:
        return self._read_ax_attr("selected", max_chars, frontmost)

    def read_focused_value(
        self, max_chars: int = 4096, frontmost: dict | None = None
    ) -> str | None:
        return self._read_ax_attr("value", max_chars, frontmost)

    def _read_ax_attr(self, kind: str, max_chars: int, frontmost: dict | None = None) -> str | None:
        try:
            from ApplicationServices import (  # type: ignore[import]  # noqa: PLC0415
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
                kAXFocusedUIElementAttribute,
                kAXSelectedTextAttribute,
                kAXValueAttribute,
            )

            info = frontmost if frontmost is not None else self.frontmost()
            pid = info.get("pid")
            if not pid:
                return None

            target_attr = kAXSelectedTextAttribute if kind == "selected" else kAXValueAttribute
            app_elem = AXUIElementCreateApplication(pid)

            # Two-hop: app element → focused element → target attribute
            err, focused = AXUIElementCopyAttributeValue(
                app_elem, kAXFocusedUIElementAttribute, None
            )
            if err != 0 or focused is None:
                return None

            err, value = AXUIElementCopyAttributeValue(focused, target_attr, None)
            if err != 0 or value is None:
                return None

            text = str(value).strip()
            return text[:max_chars] if text else None
        except Exception:
            # AX not authorised, pyobjc absent, or the app does not expose a value — all silent
            return None
