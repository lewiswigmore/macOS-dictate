from __future__ import annotations

import datetime
import io
import json
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import rumps

from dictate.config import Config
from dictate.history import last as history_last
from dictate.hotkey_config import format_combo_glyph
from dictate.icons import apply_to_app, apply_to_menu_item, write_brand_template_png
from dictate.logging_setup import get_logger

log = get_logger(__name__)

_APP_VERSION = "0.1.0"

_HOTKEY_MODES: list[tuple[str, str]] = [
    ("auto", "Auto (hold or tap)"),
    ("hold", "Hold-to-talk"),
    ("toggle", "Tap to toggle"),
]

_ASR_MODELS: list[tuple[str, str]] = [
    ("tiny.en", "tiny.en — fastest, lower accuracy"),
    ("base.en", "base.en — faster"),
    ("small.en", "small.en — balanced"),
    ("distil-small.en", "distil-small.en — fast, distilled"),
    ("distil-medium.en", "distil-medium.en — accurate + fast (default)"),
    ("medium.en", "medium.en — most accurate, slowest"),
]

_ASR_ENGINES: list[tuple[str, str]] = [
    ("faster-whisper", "faster-whisper (default, custom vocab)"),
    ("apple", "Apple Speech (fastest, on-device)"),
]

_RECENT_MAX = 5
_PRESET_REFRESH_S = 3.0
_RECENT_REFRESH_S = 5.0

_STATE_LABELS: dict[str, str] = {
    "idle": "Idle",
    "recording": "Recording",
    "cleaning": "Cleaning",
    "pasting": "Pasting",
}

# state name → SF Symbol catalog key (see dictate.icons.CATALOG)
_STATE_SYMBOLS: dict[str, str] = {
    "idle": "state.idle",
    "recording": "state.recording",
    "cleaning": "state.cleaning",
    "pasting": "state.pasting",
}


def _reveal_in_finder(path: str | Path) -> None:
    """Open Finder with the given file selected. Silent on failure."""
    subprocess.run(["open", "-R", str(path)], check=False)


class MenuBar:
    """rumps-based status-bar UI.

    Layout (top → bottom):
        state header                  (non-interactive, mirrors app state)
        ───
        Privacy Mode                  (primary daily toggle)
        ───
        Hotkey: ⌘H            ▶       (Set Hotkey…, Override System Shortcut)
        Feedback              ▶       (Audio Cues, Screen Indicator)
        Startup               ▶       (Launch at Login)
        Backend Status        ▶       (auto-populated by health pings)
        ───
        Show Last Transcript  ⌘L
        Open History…
        Open Config Folder
        Export Diagnostics…
        About dictate…
        ───
        Quit dictate          ⌘Q

    Submenu titles for Hotkey + Backend update dynamically so the current
    binding / active backend is visible without drilling in.
    """

    def __init__(self, config: Config, callbacks: dict[str, Callable]) -> None:
        self._config = config
        self._callbacks = callbacks
        self._health_items: dict[str, Any] = {}

        # ── state header (non-interactive) ──────────────────────────────────
        self._state_item = rumps.MenuItem("Idle")
        apply_to_menu_item(self._state_item, "state.idle")

        # ── primary daily toggle ────────────────────────────────────────────
        self._privacy_item = rumps.MenuItem("Privacy Mode", callback=self._on_privacy_toggle)
        self._privacy_item.state = 0

        # ── Hotkey submenu ──────────────────────────────────────────────────
        self._set_hotkey_item = rumps.MenuItem("Set Hotkey…", callback=self._on_set_hotkey)
        # "Override System Shortcut" — when CHECKED, dictate intercepts the
        # configured combo (e.g. Cmd+H Hide); when UNCHECKED, it's paused.
        # This is the inverse of the underlying ``pause_override`` flag.
        self._override_item = rumps.MenuItem(
            "Override System Shortcut", callback=self._on_override_toggle
        )
        self._override_item.state = int(
            not bool(config.get("hotkey.pause_override_default", False))
        )
        # Input mode submenu
        current_mode = str(config.get("hotkey.mode", "auto")).lower()
        self._mode_items: dict[str, Any] = {}
        self._mode_menu = rumps.MenuItem("Input Mode")
        for mode_id, label in _HOTKEY_MODES:
            item = rumps.MenuItem(
                label, callback=lambda s, m=mode_id: self._on_hotkey_mode_select(m)
            )
            item.state = int(mode_id == current_mode)
            self._mode_items[mode_id] = item
            self._mode_menu[mode_id] = item
        self._hotkey_menu = rumps.MenuItem(self._hotkey_menu_title())
        self._hotkey_menu.update(
            [self._set_hotkey_item, self._mode_menu, None, self._override_item]
        )

        # ── Feedback submenu ────────────────────────────────────────────────
        self._cues_item = rumps.MenuItem("Audio Cues", callback=self._on_cues_toggle)
        self._cues_item.state = int(bool(config.get("ui.audio_cues", True)))
        self._indicator_item = rumps.MenuItem(
            "Screen Indicator", callback=self._on_indicator_toggle
        )
        self._indicator_item.state = int(bool(config.get("ui.indicator", True)))
        # "Fast Mode" = bypass LLM cleanup → raw whisper output pasted directly.
        # Removes 1–3 s of perceived latency for users who prefer speed over polish.
        self._fast_item = rumps.MenuItem("Fast Mode (skip cleanup)", callback=self._on_fast_toggle)
        self._fast_item.state = int(not bool(config.get("cleanup.enabled", True)))
        self._feedback_menu = rumps.MenuItem("Feedback")
        self._feedback_menu.update([self._cues_item, self._indicator_item, None, self._fast_item])

        # ── Startup submenu ─────────────────────────────────────────────────
        self._launch_item = rumps.MenuItem("Launch at Login", callback=self._on_launch_toggle)
        self._startup_menu = rumps.MenuItem("Startup")
        self._startup_menu.update([self._launch_item])

        # ── ASR Model submenu ───────────────────────────────────────────────
        current_model = str(config.get("asr.model", "distil-medium.en"))
        self._model_items: dict[str, Any] = {}
        self._model_menu = rumps.MenuItem("ASR Model")
        for model_id, label in _ASR_MODELS:
            item = rumps.MenuItem(
                label, callback=lambda s, m=model_id: self._on_asr_model_select(m)
            )
            item.state = int(model_id == current_model)
            self._model_items[model_id] = item
            self._model_menu[model_id] = item

        # ── ASR Engine submenu ──────────────────────────────────────────────
        current_engine = str(config.get("asr.backend", "faster-whisper"))
        self._engine_items: dict[str, Any] = {}
        self._engine_menu = rumps.MenuItem("ASR Engine")
        for engine_id, label in _ASR_ENGINES:
            item = rumps.MenuItem(
                label, callback=lambda s, e=engine_id: self._on_asr_engine_select(e)
            )
            item.state = int(engine_id == current_engine)
            self._engine_items[engine_id] = item
            self._engine_menu[engine_id] = item
        # When Apple is active the per-model picker doesn't apply.
        self._apply_model_menu_enabled(current_engine != "apple")

        # ── Recent transcripts submenu ──────────────────────────────────────
        # Refreshed on a timer; clicking an entry re-pastes that text.
        self._recent_menu = rumps.MenuItem("Recent")
        self._recent_placeholder = rumps.MenuItem("(none yet)")
        try:
            self._recent_placeholder._menuitem.setEnabled_(False)
        except AttributeError:
            pass
        self._recent_menu.update([self._recent_placeholder])
        self._recent_entries: list[dict] = []

        # ── Backend Status submenu (populated by set_backend_health) ───────
        self._health_menu = rumps.MenuItem("Backend Status")

        # ── App + menu ──────────────────────────────────────────────────────
        # Pre-render the brand mark to a template PNG so rumps can apply it
        # via its supported ``icon=`` parameter. ``app._nsapp`` doesn't exist
        # until ``app.run()`` is called, so we can't reliably set the image
        # via AppKit at construction time — file-based works lazily.
        icon_path: str | None = None
        try:
            from pathlib import Path
            cache_dir = Path.home() / "Library" / "Application Support" / "dictate"
            cache_dir.mkdir(parents=True, exist_ok=True)
            candidate = str(cache_dir / "menubar-icon.png")
            if write_brand_template_png(candidate, point_height=36.0):
                icon_path = candidate
        except Exception:  # noqa: BLE001 — never let branding break the menu
            icon_path = None

        self._app = rumps.App(
            "dictate",
            None,
            icon=icon_path,
            template=True if icon_path else None,
            menu=[
                self._state_item,
                None,
                self._privacy_item,
                None,
                self._hotkey_menu,
                self._feedback_menu,
                self._model_menu,
                self._engine_menu,
                self._startup_menu,
                self._health_menu,
                None,
                self._recent_menu,
                rumps.MenuItem("Show Last Transcript", callback=self._on_show_transcript, key="l"),
                rumps.MenuItem("Open History…", callback=self._on_open_history_webui),
                rumps.MenuItem("Open Config Folder", callback=self._on_open_config),
                rumps.MenuItem("Export Diagnostics…", callback=self._on_export),
                rumps.MenuItem("About dictate…", callback=self._on_about),
                None,
                rumps.MenuItem("Quit dictate", callback=self._on_quit, key="q"),
            ],
            quit_button=None,
        )
        # Belt-and-suspenders: also try the in-memory route. Harmless if it
        # fails (the file-based icon above is the primary path).
        apply_to_app(self._app, "app")

        # State header is informational only.
        try:
            self._state_item._menuitem.setEnabled_(False)
        except AttributeError:
            pass

        # Track the most recent preset detected for the frontmost app, so we
        # only repaint the state header when it actually changes.
        self._current_preset: str = "default"
        self._last_state_label: str = "Idle"

        # Periodic refreshers (preset display + recent transcripts).
        self._preset_timer: rumps.Timer | None = None
        self._recent_timer: rumps.Timer | None = None

    # ── label helpers ─────────────────────────────────────────────────────────

    def _hotkey_menu_title(self) -> str:
        mods = list(self._config.get("hotkey.mods", ["cmd"]))
        key = str(self._config.get("hotkey.key", "h"))
        return f"Hotkey: {format_combo_glyph(mods, key)}"

    def _state_header_text(self, state_label: str) -> str:
        preset = self._current_preset
        if preset and preset != "default":
            return f"{state_label} · {preset}"
        return state_label

    # ── public setters ────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        label = _STATE_LABELS.get(state, state.capitalize())
        symbol_key = _STATE_SYMBOLS.get(state, "state.idle")
        self._last_state_label = label
        self._state_item.title = self._state_header_text(label)
        apply_to_menu_item(self._state_item, symbol_key)

    def set_warning(self, message: str) -> None:
        label = f"⚠ {message}"
        self._last_state_label = label
        self._state_item.title = self._state_header_text(label)
        apply_to_menu_item(self._state_item, "health.bad")

    def set_backend_health(self, name: str, ok: bool, latency_ms: int | None) -> None:
        lat = f" {latency_ms}ms" if latency_ms is not None else ""
        title = f"{name}:{lat}".rstrip(":") if not lat else f"{name}:{lat}"
        symbol_key = "health.ok" if ok else "health.bad"
        if name in self._health_items:
            item = self._health_items[name]
            item.title = title
        else:
            item = rumps.MenuItem(title, callback=None)
            self._health_items[name] = item
            self._health_menu[name] = item
        apply_to_menu_item(item, symbol_key)

    def set_privacy_mode(self, on: bool) -> None:
        self._privacy_item.state = int(on)

    def set_pause_override(self, on: bool) -> None:
        """``on=True`` means the override is paused → checkbox shows UNCHECKED."""
        self._override_item.state = int(not on)

    def refresh_hotkey_label(self) -> None:
        """Re-read the hotkey from config and update the submenu title."""
        self._hotkey_menu.title = self._hotkey_menu_title()

    def set_launch_at_login(self, on: bool) -> None:
        self._launch_item.state = int(on)

    def set_audio_cues(self, on: bool) -> None:
        self._cues_item.state = int(on)

    def set_indicator(self, on: bool) -> None:
        self._indicator_item.state = int(on)

    def run(self) -> None:
        # Start lightweight periodic refreshers. rumps.Timer fires on the
        # AppKit main thread (safe for menu mutations).
        try:
            self._preset_timer = rumps.Timer(self._refresh_preset_tick, _PRESET_REFRESH_S)
            self._preset_timer.start()
            self._recent_timer = rumps.Timer(self._refresh_recent_tick, _RECENT_REFRESH_S)
            self._recent_timer.start()
        except Exception:
            log.debug("could not start menubar timers", exc_info=True)
        self._app.run()

    def set_current_preset(self, preset: str) -> None:
        """Update the displayed preset label (e.g. ``code`` / ``chat``)."""
        preset = preset or "default"
        if preset == self._current_preset:
            return
        self._current_preset = preset
        self._state_item.title = self._state_header_text(self._last_state_label)

    def refresh_recent(self, entries: list[dict]) -> None:
        """Replace the contents of the Recent submenu with up-to-N entries.

        Each entry is a history.jsonl dict. We render the cleaned text
        (truncated) and re-paste it on click via the ``on_paste_text`` callback.
        """
        self._recent_entries = entries[:_RECENT_MAX]
        # Clear existing items
        for key in list(self._recent_menu.keys()):
            del self._recent_menu[key]
        if not self._recent_entries:
            ph = rumps.MenuItem("(none yet)")
            try:
                ph._menuitem.setEnabled_(False)
            except AttributeError:
                pass
            self._recent_menu["empty"] = ph
            return
        for idx, entry in enumerate(self._recent_entries):
            text = (entry.get("cleaned") or entry.get("raw") or "").strip()
            if not text:
                continue
            label = text if len(text) <= 60 else text[:57] + "…"
            item = rumps.MenuItem(label, callback=lambda s, i=idx: self._on_recent_click(i))
            self._recent_menu[f"r{idx}"] = item

    # ── menu callbacks ────────────────────────────────────────────────────────

    def _on_privacy_toggle(self, sender: Any) -> None:
        new = not bool(self._privacy_item.state)
        self._privacy_item.state = int(new)
        cb = self._callbacks.get("on_privacy_toggle")
        if cb:
            cb(new)

    def _on_override_toggle(self, sender: Any) -> None:
        # Checkbox was previously CHECKED means overriding → click → now PAUSED.
        # Old state (pre-flip) reads as ``self._override_item.state``.
        new_paused = bool(self._override_item.state)
        self._override_item.state = int(not new_paused)
        cb = self._callbacks.get("on_pause_override_toggle")
        if cb:
            cb(new_paused)

    def _on_set_hotkey(self, sender: Any) -> None:
        cb = self._callbacks.get("on_set_hotkey")
        if cb:
            cb()

    def _on_hotkey_mode_select(self, mode_id: str) -> None:
        # Single-select radio behaviour across the three mode items.
        for mid, item in self._mode_items.items():
            item.state = int(mid == mode_id)
        cb = self._callbacks.get("on_hotkey_mode_change")
        if cb:
            cb(mode_id)

    def _on_asr_model_select(self, model_id: str) -> None:
        for mid, item in self._model_items.items():
            item.state = int(mid == model_id)
        cb = self._callbacks.get("on_asr_model_change")
        if cb:
            cb(model_id)

    def _apply_model_menu_enabled(self, enabled: bool) -> None:
        for item in self._model_items.values():
            try:
                item._menuitem.setEnabled_(bool(enabled))
            except AttributeError:
                pass

    def _on_asr_engine_select(self, engine_id: str) -> None:
        for eid, item in self._engine_items.items():
            item.state = int(eid == engine_id)
        self._apply_model_menu_enabled(engine_id != "apple")
        cb = self._callbacks.get("on_asr_engine_change")
        if cb:
            cb(engine_id)

    def _on_recent_click(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._recent_entries):
            return
        entry = self._recent_entries[idx]
        text = (entry.get("cleaned") or entry.get("raw") or "").strip()
        cb = self._callbacks.get("on_paste_text")
        if cb and text:
            cb(text)

    # ── periodic refresh ──────────────────────────────────────────────────────

    def _refresh_preset_tick(self, _sender: Any) -> None:
        cb = self._callbacks.get("on_request_current_preset")
        if not cb:
            return
        try:
            preset = cb() or "default"
        except Exception:
            log.debug("preset probe failed", exc_info=True)
            return
        self.set_current_preset(str(preset))

    def _refresh_recent_tick(self, _sender: Any) -> None:
        try:
            entries = history_last(self._config, _RECENT_MAX * 3)
        except Exception:
            log.debug("history read failed", exc_info=True)
            return
        # Only show utterances (skip "correction" rows). Keep most-recent first.
        utterances = [e for e in entries if e.get("type", "utterance") == "utterance"]
        self.refresh_recent(list(reversed(utterances)))

    def _on_launch_toggle(self, sender: Any) -> None:
        new = not bool(self._launch_item.state)
        cb = self._callbacks.get("on_launch_at_login_toggle")
        accepted = True
        if cb:
            result = cb(new)
            # callback may return False to reject the toggle (e.g. install failed)
            accepted = result is not False
        if accepted:
            self._launch_item.state = int(new)

    def _on_cues_toggle(self, sender: Any) -> None:
        new = not bool(self._cues_item.state)
        self._cues_item.state = int(new)
        cb = self._callbacks.get("on_audio_cues_toggle")
        if cb:
            cb(new)

    def _on_indicator_toggle(self, sender: Any) -> None:
        new = not bool(self._indicator_item.state)
        self._indicator_item.state = int(new)
        cb = self._callbacks.get("on_indicator_toggle")
        if cb:
            cb(new)

    def _on_fast_toggle(self, sender: Any) -> None:
        # Checkbox CHECKED → Fast Mode ON → cleanup DISABLED.
        new_fast = not bool(self._fast_item.state)
        self._fast_item.state = int(new_fast)
        cb = self._callbacks.get("on_fast_mode_toggle")
        if cb:
            cb(new_fast)

    def set_fast_mode(self, on: bool) -> None:
        self._fast_item.state = int(on)

    def _on_show_transcript(self, sender: Any) -> None:
        cb = self._callbacks.get("on_show_last_transcript")
        if cb:
            cb()

    def _on_open_history_webui(self, sender: Any) -> None:
        cb = self._callbacks.get("on_open_history_webui")
        if cb:
            cb()

    def _on_open_config(self, sender: Any) -> None:
        cb = self._callbacks.get("on_open_config")
        if cb:
            cb()

    def _on_export(self, sender: Any) -> None:
        try:
            path = self._build_diagnostics_archive()
            log.info("diagnostics exported to %s", path)
            _reveal_in_finder(path)
        except Exception as exc:
            log.exception("diagnostics export failed: %s", exc)

    def _on_quit(self, sender: Any) -> None:
        cb = self._callbacks.get("on_quit")
        if cb:
            cb()
        rumps.quit_application()

    def _on_about(self, sender: Any) -> None:
        # Show the brand logo in the alert if it's on disk. Resolved relative to
        # the repo root via the active Config so a packaged build still works.
        icon_path: str | None = None
        try:
            candidate = self._config.root / "assets" / "logo-256.png"
            if candidate.is_file():
                icon_path = str(candidate)
        except Exception:  # noqa: BLE001 — never let branding break the menu
            icon_path = None

        kwargs: dict[str, Any] = {
            "title": "dictate",
            "message": (
                f"Version {_APP_VERSION}\n\n"
                "Local-first voice typing for macOS.\n"
                "Press your hotkey to dictate into any focused app."
            ),
            "ok": "OK",
        }
        if icon_path:
            kwargs["icon_path"] = icon_path
        rumps.alert(**kwargs)

    # ── diagnostics builder ───────────────────────────────────────────────────

    def _build_diagnostics_archive(self) -> str:
        """Build ~/Desktop/dictate-diagnostics-{ts}.tgz and return its path."""
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = Path.home() / "Desktop" / f"dictate-diagnostics-{ts}.tgz"

        with tarfile.open(out_path, "w:gz") as tar:
            self._add_logs(tar)
            self._add_history(tar)
            self._add_config(tar)
            self._add_system_profile(tar)

        return str(out_path)

    @staticmethod
    def _tar_add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    def _add_logs(self, tar: tarfile.TarFile) -> None:
        logs_dir = Path(self._config.log_path).parent
        if not logs_dir.exists():
            return
        for log_file in sorted(logs_dir.glob("*.log*")):
            try:
                lines = log_file.read_text(errors="replace").splitlines()[-50:]
                self._tar_add_bytes(tar, f"logs/{log_file.name}", "\n".join(lines).encode())
            except Exception as exc:
                log.warning("skipping log %s: %s", log_file.name, exc)

    def _add_history(self, tar: tarfile.TarFile) -> None:
        history_path = Path(self._config.history_path)
        if not history_path.exists():
            return
        try:
            from dictate.redact import Redactor

            redactor = Redactor(self._config.redact_patterns)
        except ImportError:
            self._tar_add_bytes(
                tar,
                "history.jsonl",
                b"# history omitted: redact module not available\n",
            )
            return

        raw_lines = history_path.read_text(errors="replace").splitlines()[-5:]
        redacted: list[str] = []
        for line in raw_lines:
            try:
                entry = json.loads(line)
                clean = {
                    k: redactor.redact(str(v))[0] if isinstance(v, str) else v
                    for k, v in entry.items()
                }
                redacted.append(json.dumps(clean, ensure_ascii=False))
            except Exception:
                redacted.append("[parse error]")

        self._tar_add_bytes(tar, "history.jsonl", "\n".join(redacted).encode())

    def _add_config(self, tar: tarfile.TarFile) -> None:
        cfg_dir = Path(self._config.root) / "config"
        if not cfg_dir.exists():
            return
        _EXCLUDED = {"personal.txt", "work.txt"}
        for f in sorted(cfg_dir.iterdir()):
            if f.name in _EXCLUDED or not f.is_file():
                continue
            try:
                self._tar_add_bytes(tar, f"config/{f.name}", f.read_bytes())
            except Exception as exc:
                log.warning("skipping config %s: %s", f.name, exc)

    def _add_system_profile(self, tar: tarfile.TarFile) -> None:
        try:
            result = subprocess.run(
                ["system_profiler", "SPSoftwareDataType"],
                capture_output=True,
                timeout=1,
                text=True,
            )
            data = result.stdout.encode()
        except Exception:
            data = b"[unavailable]\n"
        self._tar_add_bytes(tar, "system_profiler.txt", data)
