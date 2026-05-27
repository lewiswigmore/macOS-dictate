from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn

from dictate import url_scheme
from dictate.asr import ASR
from dictate.audio_cues import AudioCues
from dictate.cleanup import CleanupClient
from dictate.commands import CommandParser
from dictate.config import Config, load_config, was_load_failure
from dictate.conflicts import Conflict
from dictate.conflicts import check_all as check_conflicts
from dictate.context import ContextProbe
from dictate.endpoint import EndpointWatcher
from dictate.health import HealthMonitor
from dictate.history import append as history_append
from dictate.history import reveal_last_in_finder, set_write_error_callback
from dictate.hotkey import HotkeyTap
from dictate.hotkey_config import ComboParseError, format_combo, parse_combo, write_hotkey
from dictate.hud import HUD
from dictate.indicator import Indicator
from dictate.launch_agent import (
    install as install_launch_agent,
)
from dictate.launch_agent import (
    is_installed as launch_agent_installed,
)
from dictate.launch_agent import (
    uninstall as uninstall_launch_agent,
)
from dictate.learn import LearnWatcher
from dictate.logging_setup import get_logger, log_metrics
from dictate.logging_setup import setup as setup_logging
from dictate.menubar import MenuBar
from dictate.onboarding import OnboardingWizard
from dictate.permissions import Permissions
from dictate.punctuate import smart_punctuate
from dictate.recorder import MicRecorder
from dictate.redact import Redactor
from dictate.typer import Typer
from dictate.vad import VAD
from dictate.vocab import as_initial_prompt, load_vocab
from dictate.webui.server import create_app

try:
    from dictate.config import was_load_failure
except ImportError:

    def was_load_failure() -> tuple[bool, str | None]:
        return False, None


try:
    from dictate.history import set_write_error_callback
except ImportError:

    def set_write_error_callback(_callback) -> None:  # noqa: ANN001
        return None


try:
    from dictate.replacements import apply as apply_replacements
    from dictate.replacements import load_layered as load_replacements_layered
except ImportError:

    def apply_replacements(text: str, _replacements: object) -> str:
        return text

    def load_replacements_layered(*_paths: Path) -> list[object]:
        return []


log = get_logger(__name__)

_MIN_AUDIO_SAMPLES_AFTER_VAD = 1600  # 0.1 s at 16 kHz
_LOW_CONFIDENCE_HUD_MS = 1.2
_WEBUI_HOST = "127.0.0.1"
_WEBUI_PORT = 47843
_WEBUI_URL = f"http://{_WEBUI_HOST}:{_WEBUI_PORT}"
_APPLE_EVENT_DIRECT_OBJECT = b"----"
_INTERNET_EVENT_CLASS = b"GURL"
_AE_GET_URL = b"GURL"


def fourcc(value: bytes) -> int:
    if len(value) != 4:
        raise ValueError("fourcc values must be exactly 4 bytes")
    return int.from_bytes(value, "big")


@dataclass
class _PipelineCtx:
    """Mutable state passed between pipeline phases."""

    raw: str = ""
    cleaned: str = ""
    preset: str = "default"
    frontmost: dict[str, Any] = field(default_factory=dict)
    selection: str | None = None
    vocab: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    redactions: list[dict] = field(default_factory=list)


class App:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        setup_logging(
            level=self.config.get("logging.level", "INFO"),
            json_logs=bool(self.config.get("logging.json", True)),
            file=self.config.log_path,
            rotate_days=int(self.config.get("logging.rotate_days", 7)),
        )
        self.startup_conflicts: list[Conflict] = []

        self.permissions = Permissions()
        self.redactor = Redactor(self.config.redact_patterns)
        self.replacements = load_replacements_layered(*self._replacement_paths())
        self.commands = CommandParser(self.config.commands)
        self.context = ContextProbe(self.config)
        self.recorder = MicRecorder()
        self.vad = VAD(self.config)
        # Auto-endpoint uses an isolated VAD instance so its state machine
        # doesn't interfere with the post-stop trim_silence pass. It also
        # honours a dedicated `vad.auto_endpoint.min_silence_ms` override so
        # the endpoint cutoff can be more lenient than the streaming VAD.
        self.endpoint_vad = VAD(self.config)
        endpoint_silence_ms = self.config.get("vad.auto_endpoint.min_silence_ms")
        if endpoint_silence_ms is not None:
            try:
                self.endpoint_vad._min_silence_ms = float(endpoint_silence_ms)
            except (TypeError, ValueError):
                pass
        self.asr = ASR(self.config)
        self.cleanup = CleanupClient(self.config)
        self.typer = Typer()
        self.hud = HUD(self.config)
        self.cues = AudioCues(self.config)
        self.indicator = Indicator(self.config)
        self.learn = LearnWatcher(
            self.config,
            history_appender=lambda e: history_append(self.config, e),
            context=self.context,
        )

        self.health = HealthMonitor(self.config, on_change=self._on_health_change)
        self.menubar = MenuBar(
            self.config,
            callbacks={
                "on_privacy_toggle": self._on_privacy_toggle,
                "on_pause_override_toggle": self._on_pause_override_toggle,
                "on_show_last_transcript": self._on_show_last_transcript,
                "on_open_history_webui": self._on_open_history_webui,
                "on_open_config": self._on_open_config,
                "on_set_hotkey": self._on_set_hotkey,
                "on_launch_at_login_toggle": self._on_launch_at_login_toggle,
                "on_audio_cues_toggle": self._on_audio_cues_toggle,
                "on_indicator_toggle": self._on_indicator_toggle,
                "on_fast_mode_toggle": self._on_fast_mode_toggle,
                "on_hotkey_mode_change": self._on_hotkey_mode_change,
                "on_asr_model_change": self._on_asr_model_change,
                "on_asr_engine_change": self._on_asr_engine_change,
                "on_paste_text": self._on_paste_text,
                "on_request_current_preset": self._current_preset,
                "on_quit": self.shutdown,
            },
        )
        self.menubar.set_launch_at_login(launch_agent_installed())
        set_write_error_callback(self._on_history_write_error)
        failed, error = was_load_failure()
        if failed:
            self._on_config_load_error(error)

        self.hotkey = HotkeyTap(
            self.config,
            on_start=self._on_hotkey_start,
            on_stop=self._on_hotkey_stop,
            on_cancel=self._on_hotkey_cancel,
        )

        self._pipeline_lock = threading.Lock()
        self._last_transcript: dict | None = None
        self._shutting_down = False
        self._endpoint_watcher: EndpointWatcher | None = None
        self._webui_server: uvicorn.Server | None = None
        self._webui_thread: threading.Thread | None = None
        self._webui_lock = threading.Lock()
        self._url_event_handler: object | None = None

    def _replacement_path(self) -> Path:
        configured = Path(
            str(self.config.get("vocab.replacements", "config/vocab/replacements.txt"))
        )
        if configured.is_absolute():
            return configured
        return self.config.root / configured

    def _replacement_paths(self) -> list[Path]:
        """Return the ordered list of replacement files to merge.

        Layers, lowest precedence first: legacy `.txt`, global `.yaml`,
        then a per-preset YAML if it exists.
        """
        root = self.config.root
        paths: list[Path] = []
        legacy_txt = self._replacement_path()
        if legacy_txt.exists():
            paths.append(legacy_txt)
        global_yaml = root / "config" / "vocab" / "replacements.yaml"
        if global_yaml.exists():
            paths.append(global_yaml)
        return paths

    def _preset_replacement_path(self, preset: str) -> Path:
        return self.config.root / "config" / "vocab" / f"{preset}.replacements.yaml"

    def _rules_for_preset(self, preset: str) -> list[object]:
        """Merge global replacements with the active preset's override."""
        preset_path = self._preset_replacement_path(preset)
        if not preset_path.exists():
            return list(self.replacements)
        return load_replacements_layered(*self._replacement_paths(), preset_path)

    # ----------------------------------------------------------------- lifecycle

    def boot(self) -> None:
        self._check_startup_conflicts()
        wizard = OnboardingWizard(
            self.config,
            self.permissions,
            backend_pinger=self.health.ping_once,
        )
        if wizard.needs_wizard():
            log.info("Running onboarding wizard")
            try:
                wizard.run()
            except Exception as e:
                log.warning("Onboarding wizard failed: %s", e)

        missing = [k for k, ok in self.permissions.all_granted().items() if not ok]
        if missing:
            log.error("Missing permissions: %s. Open System Settings and grant them.", missing)

        self.health.start()
        self.hotkey.start()
        self._register_url_event_handler()
        self._prewarm_models()
        log.info("dictate ready. Hotkey active.")

    def _register_url_event_handler(self) -> None:
        try:
            from Foundation import NSAppleEventManager, NSObject
        except Exception:
            log.debug("Apple Event URL handler unavailable", exc_info=True)
            return

        controller = self

        class URLAppleEventHandler(NSObject):  # type: ignore[misc, valid-type]
            def handleURL_withReplyEvent_(self, event, _reply) -> None:  # noqa: ANN001, N802
                try:
                    descriptor = event.paramDescriptorForKeyword_(
                        fourcc(_APPLE_EVENT_DIRECT_OBJECT)
                    )
                    url = descriptor.stringValue() if descriptor is not None else None
                    if url:
                        url_scheme.dispatch(str(url), controller)
                except Exception:
                    log.exception("Apple Event URL dispatch failed")

        try:
            handler = URLAppleEventHandler.alloc().init()
            manager = NSAppleEventManager.sharedAppleEventManager()
            manager.setEventHandler_andSelector_forEventClass_andEventID_(
                handler,
                "handleURL:withReplyEvent:",
                fourcc(_INTERNET_EVENT_CLASS),
                fourcc(_AE_GET_URL),
            )
            self._url_event_handler = handler
            log.info("registered dictate:// Apple Event handler")
        except Exception:
            log.debug("Apple Event URL handler registration failed", exc_info=True)

    def _check_startup_conflicts(self) -> None:
        def _check() -> None:
            try:
                self.startup_conflicts = check_conflicts()
            except Exception:
                log.debug("startup conflict check failed", exc_info=True)
                return
            for conflict in self.startup_conflicts:
                if conflict.severity in {"warning", "error"}:
                    log.warning(
                        "Startup conflict: %s — %s Suggestion: %s",
                        conflict.name,
                        conflict.detail,
                        conflict.suggestion,
                    )
            warnings = [c for c in self.startup_conflicts if c.severity in {"warning", "error"}]
            if warnings:
                try:
                    self.menubar.set_warning(f"{len(warnings)} startup conflict(s)")
                except Exception:
                    log.debug("startup conflict badge failed", exc_info=True)

        threading.Thread(target=_check, daemon=True, name="startup-conflicts").start()

    def _prewarm_models(self) -> None:
        """Load whisper + silero-vad in the background so first dictation has no cold-start."""

        def _warm() -> None:
            try:
                if self.config.get("asr.backend", "faster-whisper") == "apple":
                    # Apple needs auth before load — request it (which may
                    # surface the system prompt) and then load.
                    self._request_apple_permission_async()
                else:
                    t0 = time.monotonic()
                    self.asr.load()
                    log.info("ASR pre-warmed in %d ms", int((time.monotonic() - t0) * 1000))
            except Exception as e:
                log.warning("ASR pre-warm failed: %s", e)
            try:
                t0 = time.monotonic()
                self.vad.load()
                log.info("VAD pre-warmed in %d ms", int((time.monotonic() - t0) * 1000))
            except Exception as e:
                log.warning("VAD pre-warm failed: %s", e)

        threading.Thread(target=_warm, daemon=True, name="prewarm").start()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("Shutting down")
        for fn in (self.hotkey.stop, self.health.stop, self.recorder.cancel):
            try:
                fn()
            except Exception:
                log.debug("shutdown step failed", exc_info=True)
        self._shutdown_webui()
        sys.exit(0)

    # ------------------------------------------------------------ automation hooks

    def start_recording(self) -> None:
        if self.hotkey.is_recording:
            return
        self._set_hotkey_recording(True)
        self._on_hotkey_start()

    def stop_recording(self) -> None:
        if not self.hotkey.is_recording:
            return
        self._set_hotkey_recording(False)
        self._on_hotkey_stop()

    def toggle_recording(self) -> None:
        if self.hotkey.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def open_webui(self, entry_id: str | None = None) -> None:
        self._on_open_history_webui(entry_id=entry_id)

    def _set_hotkey_recording(self, recording: bool) -> None:
        try:
            sm = self.hotkey._state_machine  # type: ignore[attr-defined]
            with sm._lock:  # type: ignore[attr-defined]
                sm._is_recording = recording  # type: ignore[attr-defined]
                sm._state = type(sm._state).IDLE  # type: ignore[attr-defined]
                sm._h_pressed = False  # type: ignore[attr-defined]
        except Exception:
            log.debug("could not sync hotkey state for automation", exc_info=True)

    # ------------------------------------------------------------ menubar hooks

    def _on_history_write_error(self, event: dict) -> None:
        log.error("history write error event: %s", event, extra={"extras": event})
        try:
            self.menubar.set_warning("History write failed")
        except Exception:
            log.debug("history write-error badge failed", exc_info=True)

    def _on_config_load_error(self, error: str | None) -> None:
        log.error("config load failed; running with defaults: %s", error)
        try:
            self.menubar.set_warning("Config load failed")
        except Exception:
            log.debug("config load-failure badge failed", exc_info=True)

    def _on_privacy_toggle(self, enabled: bool) -> None:
        new_backend = (
            self.config.privacy_backend_name if enabled else self.config.default_backend_name
        )
        self.config.settings.setdefault("cleanup", {})["backend"] = new_backend
        log.info("Privacy mode %s. Active backend: %s", "ON" if enabled else "OFF", new_backend)

    def _on_pause_override_toggle(self, paused: bool) -> None:
        self.hotkey.set_pause_override(paused)
        log.info("Cmd+H override paused=%s", paused)

    def _on_show_last_transcript(self) -> None:
        reveal_last_in_finder(self.config)

    def _on_open_history_webui(self, entry_id: str | None = None) -> None:
        open_delay = 0.0
        with self._webui_lock:
            if self._webui_thread is None or not self._webui_thread.is_alive():
                log.info("starting webui on %s", _WEBUI_URL)
                try:
                    config = uvicorn.Config(
                        create_app(self.config),
                        host=_WEBUI_HOST,
                        port=_WEBUI_PORT,
                        log_level="warning",
                    )
                    server = uvicorn.Server(config)
                    self._webui_server = server
                    self._webui_thread = threading.Thread(
                        target=self._run_webui_server,
                        args=(server,),
                        daemon=True,
                        name="dictate-webui",
                    )
                    self._webui_thread.start()
                    open_delay = 0.5
                except Exception:
                    log.exception("failed to start webui")
                    return
        threading.Thread(
            target=self._open_history_webui,
            args=(open_delay, entry_id),
            daemon=True,
            name="dictate-webui-open",
        ).start()

    def _run_webui_server(self, server: uvicorn.Server) -> None:
        try:
            server.run()
        except Exception:
            log.exception("webui server failed")

    def _open_history_webui(self, delay: float, entry_id: str | None = None) -> None:
        if delay:
            time.sleep(delay)
        url = _WEBUI_URL if entry_id is None else f"{_WEBUI_URL}/entry/{quote(entry_id, safe='')}"
        subprocess.run(["open", url], check=False)

    def _shutdown_webui(self) -> None:
        try:
            server = self._webui_server
            thread = self._webui_thread
            if server is not None:
                server.should_exit = True
            if thread is not None and thread.is_alive():
                thread.join(timeout=2)
        except Exception:
            log.exception("failed to shut down webui")

    def _on_open_config(self) -> None:
        subprocess.run(["open", str(self.config.root / "config")], check=False)

    def _on_set_hotkey(self) -> bool:
        """Prompt for a new combo, persist it, hot-reload the tap."""
        import rumps

        current = format_combo(
            list(self.config.get("hotkey.mods", ["cmd"])),
            str(self.config.get("hotkey.key", "h")),
        )
        prompt = rumps.Window(
            message=(
                "Enter a hotkey combo as `mod+mod+key`.\n"
                "Modifiers: cmd, shift, option, control. "
                "Keys: a–z, 0–9, space, escape, return, tab, delete."
            ),
            title="Set dictate hotkey",
            default_text=current,
            ok="Save",
            cancel="Cancel",
            dimensions=(320, 24),
        )
        resp = prompt.run()
        if resp.clicked != 1:
            return False
        try:
            mods, key = parse_combo(resp.text)
        except ComboParseError as exc:
            rumps.alert(title="Invalid hotkey", message=str(exc))
            return False

        settings_path = self.config.root / "config" / "settings.yaml"
        try:
            write_hotkey(settings_path, mods, key)
        except Exception as exc:
            log.exception("failed to persist hotkey: %s", exc)
            rumps.alert(title="Could not save hotkey", message=str(exc))
            return False

        # Hot-reload: re-read settings and rebuild the state machine.
        self.config = load_config(self.config.root)
        self.hotkey._config = self.config  # type: ignore[attr-defined]
        self.hotkey.reload()
        self.menubar.refresh_hotkey_label()
        log.info("hotkey changed to %s", format_combo(mods, key))
        return True

    def _on_launch_at_login_toggle(self, enable: bool) -> bool:
        import rumps

        try:
            if enable:
                install_launch_agent(self.config)
                rumps.notification(
                    title="dictate",
                    subtitle="Launch at Login enabled",
                    message="dictate will start automatically when you log in.",
                )
            else:
                uninstall_launch_agent()
                rumps.notification(
                    title="dictate",
                    subtitle="Launch at Login disabled",
                    message="dictate will no longer start automatically.",
                )
            return True
        except Exception as exc:
            log.exception("launch-at-login toggle failed: %s", exc)
            rumps.alert(title="Could not update Launch at Login", message=str(exc))
            return False

    def _on_audio_cues_toggle(self, enable: bool) -> None:
        self.cues.set_enabled(enable)
        log.info("audio cues %s", "enabled" if enable else "disabled")

    def _on_indicator_toggle(self, enable: bool) -> None:
        self.indicator.set_enabled(enable)
        log.info("screen indicator %s", "enabled" if enable else "disabled")

    def _on_fast_mode_toggle(self, fast: bool) -> None:
        # Persists to user_prefs.yaml so the choice survives restart.
        # cleanup.enabled is read via Config.get() on every pipeline pass.
        try:
            self.config.persist_pref("cleanup.enabled", not fast)
        except Exception as exc:
            log.exception("could not persist fast mode pref: %s", exc)
            self.config.set("cleanup.enabled", not fast)
        log.info(
            "fast mode %s (LLM cleanup %s)",
            "ON" if fast else "OFF",
            "disabled" if fast else "enabled",
        )

    def _on_hotkey_mode_change(self, mode_id: str) -> None:
        try:
            self.config.persist_pref("hotkey.mode", mode_id)
        except Exception:
            log.exception("could not persist hotkey mode")
            self.config.set("hotkey.mode", mode_id)
        try:
            self.hotkey.reload()
        except Exception:
            log.exception("hotkey reload failed after mode change")
        log.info("hotkey input mode → %s", mode_id)

    def _on_asr_engine_change(self, engine_id: str) -> None:
        try:
            self.config.persist_pref("asr.backend", engine_id)
        except Exception:
            log.exception("could not persist asr backend")
            self.config.set("asr.backend", engine_id)
        try:
            self.asr.reload()
        except Exception:
            log.exception("asr reload failed")

        if engine_id == "apple":
            # Apple needs explicit auth; run on the main thread so the system
            # prompt can surface (rumps drives the NSApp run loop here).
            self._request_apple_permission_async()
        else:
            threading.Thread(
                target=self._prewarm_asr_async,
                args=(self.config.get("asr.model", "small.en"),),
                daemon=True,
                name="asr-prewarm",
            ).start()
        log.info("asr backend → %s", engine_id)

    def _request_apple_permission_async(self) -> None:
        threading.Thread(
            target=self._apple_permission_worker, daemon=True, name="apple-auth"
        ).start()

    def _apple_permission_worker(self) -> None:
        try:
            from dictate.asr_apple import (
                AUTH_AUTHORIZED,
                current_auth_status,
                request_authorization_blocking,
            )
        except Exception:
            log.exception("apple speech module unavailable")
            return

        status = current_auth_status()
        if status != AUTH_AUTHORIZED:
            status = request_authorization_blocking(timeout=30.0)

        if status != AUTH_AUTHORIZED:
            log.warning("apple speech auth status = %s", status)
            self._safe_notify(
                subtitle="Speech permission not granted",
                message=(
                    "Open System Settings → Privacy & Security → "
                    "Speech Recognition to enable, then re-select Apple Speech."
                ),
            )
            return

        try:
            self.asr.load()
        except Exception as exc:
            log.exception("apple engine load failed")
            self._safe_notify(
                subtitle="Apple Speech load failed",
                message=str(exc)[:200],
            )
            return

        self._safe_notify(
            subtitle="ASR engine: Apple Speech",
            message="On-device recognizer ready.",
        )

    @staticmethod
    def _safe_notify(*, subtitle: str, message: str) -> None:
        import rumps

        try:
            rumps.notification(title="dictate", subtitle=subtitle, message=message)
        except Exception:
            log.debug("notification failed", exc_info=True)

    def _on_asr_model_change(self, model_id: str) -> None:
        try:
            self.config.persist_pref("asr.model", model_id)
        except Exception:
            log.exception("could not persist asr model")
            self.config.set("asr.model", model_id)
        try:
            self.asr.reload()
            threading.Thread(
                target=self._prewarm_asr_async,
                args=(model_id,),
                daemon=True,
                name="asr-prewarm",
            ).start()
        except Exception:
            log.exception("asr reload failed")
        log.info("asr model → %s (loading in background)", model_id)

    def _prewarm_asr_async(self, model_id: str) -> None:
        import rumps

        try:
            t0 = time.monotonic()
            self.asr.load()
            elapsed = int((time.monotonic() - t0) * 1000)
            log.info("ASR re-warmed in %d ms (model=%s)", elapsed, model_id)
            try:
                rumps.notification(
                    title="dictate",
                    subtitle=f"ASR model: {model_id}",
                    message=f"Loaded in {elapsed} ms — ready to dictate.",
                )
            except Exception:
                log.debug("notification failed", exc_info=True)
        except Exception:
            log.exception("ASR pre-warm failed for %s", model_id)
            try:
                rumps.notification(
                    title="dictate",
                    subtitle="ASR model load failed",
                    message=f"Could not load {model_id}. Keeping previous model active.",
                )
            except Exception:
                log.debug("notification failed", exc_info=True)

    def _on_paste_text(self, text: str) -> None:
        """Re-paste a previously-dictated transcript from the Recent menu."""
        try:
            self.typer.paste(text)
            log.info("re-pasted recent transcript (%d chars)", len(text))
        except Exception:
            log.exception("re-paste failed")

    def _current_preset(self) -> str:
        """Probe the frontmost app and return the matching preset id.

        Called periodically by the menubar to show the active preset hint.
        Best-effort: returns "default" on any failure.
        """
        try:
            front = self.context.frontmost()
            bundle = front.get("bundle_id") if isinstance(front, dict) else None
            return self.config.preset_for_bundle(bundle)
        except Exception:
            return "default"

    # ------------------------------------------------------------------- health

    def _remember_inserted(self, text: str) -> None:
        remember = getattr(self.commands, "remember_inserted", None)
        if callable(remember):
            remember(text)

    def _on_health_change(self, status: dict) -> None:
        for name, info in status.items():
            try:
                self.menubar.set_backend_health(name, bool(info.get("ok")), info.get("latency_ms"))
            except Exception:
                log.debug("set_backend_health failed for %s", name, exc_info=True)

    # ------------------------------------------------------------ hotkey hooks

    def _on_hotkey_start(self) -> None:
        try:
            self.hud.show_state("recording")
            self.menubar.set_state("recording")
            self.recorder.start()
            self.cues.play("start")
            self.indicator.flash("activated")
            self._start_endpoint_watcher()
            log.info("Recording started")
        except Exception as e:
            log.exception("Failed to start recording: %s", e)
            self.hud.hide()

    def _on_hotkey_stop(self) -> None:
        self._stop_endpoint_watcher()
        self.cues.play("end")
        self.indicator.flash("deactivated")
        threading.Thread(target=self._run_pipeline, daemon=True, name="pipeline").start()

    def _on_hotkey_cancel(self) -> None:
        log.info("Recording cancelled")
        self._stop_endpoint_watcher()
        try:
            self.recorder.cancel()
        finally:
            self.cues.play("cancel")
            self.indicator.flash("cancelled")
            self.hud.hide()
            self.menubar.set_state("idle")

    # ----------------------------------------------------------- auto-endpoint

    def _start_endpoint_watcher(self) -> None:
        if not bool(self.config.get("vad.auto_endpoint.enabled", True)):
            return
        max_ms = int(self.config.get("vad.auto_endpoint.max_recording_ms", 60_000))
        self._endpoint_watcher = EndpointWatcher(
            recorder=self.recorder,
            vad=self.endpoint_vad,
            on_endpoint=self._auto_endpoint_fire,
            max_recording_ms=max_ms,
            is_held=self._hotkey_is_held,
        )
        self._endpoint_watcher.start()

    def _hotkey_is_held(self) -> bool:
        try:
            sm = self.hotkey._state_machine  # type: ignore[attr-defined]
            return bool(sm.is_held)
        except Exception:
            return False

    def _stop_endpoint_watcher(self) -> None:
        w = self._endpoint_watcher
        self._endpoint_watcher = None
        if w is not None:
            w.stop()

    def _auto_endpoint_fire(self) -> None:
        """Synthesise a hotkey-stop from the watcher thread.

        The hotkey state machine is normally driven by key events; we have to
        manually reset its flags so subsequent presses behave correctly.
        """
        try:
            sm = self.hotkey._state_machine  # type: ignore[attr-defined]
            with sm._lock:  # type: ignore[attr-defined]
                if not sm._is_recording:  # type: ignore[attr-defined]
                    return
                sm._is_recording = False  # type: ignore[attr-defined]
                sm._state = type(sm._state).IDLE  # type: ignore[attr-defined]
                sm._h_pressed = False  # type: ignore[attr-defined]
        except Exception:
            log.debug("could not reset hotkey state machine after auto-endpoint", exc_info=True)
        self._on_hotkey_stop()

    # ----------------------------------------------------------------- pipeline

    def _run_pipeline(self) -> None:
        if not self._pipeline_lock.acquire(blocking=False):
            log.warning("Pipeline already running; dropping concurrent stop")
            return

        t0 = time.monotonic()
        ctx = _PipelineCtx()
        try:
            audio = self._capture_and_trim()
            if audio is None:
                return

            if not self._phase_transcribe(audio, ctx):
                return

            command = self.commands.parse(ctx.raw)
            if command is not None:
                self._handle_command(command, ctx)
                return

            self._phase_redact(ctx)
            self._phase_cleanup(ctx)
            self._phase_paste(ctx)
            ctx.metrics["duration_ms"] = int((time.monotonic() - t0) * 1000)
            # One-line timing summary so users can see where latency comes from
            # without grepping JSON. Format: "pipeline: asr=480 cleanup=2210 paste=8 total=2870 ms"
            m = ctx.metrics
            log.info(
                "pipeline: asr=%s cleanup=%s paste=%s total=%s ms%s",
                m.get("asr_ms", "?"),
                m.get("cleanup_skipped") or m.get("cleanup_ms", "?"),
                m.get("paste_ms", "?"),
                m.get("duration_ms", "?"),
                f"  ({len(ctx.cleaned)} chars)" if ctx.cleaned else "",
            )
            self._phase_persist(ctx)
        except Exception as e:
            log.exception("Pipeline error: %s", e)
        finally:
            self.hud.hide()
            try:
                self.menubar.set_state("idle")
            except Exception:
                log.debug("set_state idle failed", exc_info=True)
            self._pipeline_lock.release()

    def _capture_and_trim(self):
        audio = self.recorder.stop()
        if audio is None or len(audio) == 0:
            log.info("Empty audio; nothing to do")
            return None

        # Capture-time diagnostics — surfaces mic-input problems (wrong device,
        # muted input, denied permission) that VAD alone can't distinguish from
        # legitimate silence. RMS < 0.001 = effectively dead mic.
        try:
            import numpy as _np

            raw_secs = len(audio) / 16000.0
            peak = float(_np.max(_np.abs(audio))) if len(audio) else 0.0
            rms = float(_np.sqrt(_np.mean(audio.astype(_np.float32) ** 2))) if len(audio) else 0.0
            log.info(
                "captured audio: %.2fs  peak=%.4f  rms=%.4f",
                raw_secs,
                peak,
                rms,
            )
            if rms < 0.001:
                log.warning(
                    "mic input is effectively silent (rms=%.5f). Check System "
                    "Settings → Privacy & Security → Microphone for the dictate "
                    "process, and that the right input device is selected.",
                    rms,
                )
        except Exception:  # noqa: BLE001 — diagnostics must never break the pipeline
            pass

        if bool(self.config.get("vad.enabled", True)):
            try:
                audio = self.vad.trim_silence(audio)
            except Exception as e:
                log.warning("VAD trim failed: %s", e)

        if len(audio) < _MIN_AUDIO_SAMPLES_AFTER_VAD:
            log.info("Audio too short after VAD; skipping")
            return None
        return audio

    def _phase_transcribe(self, audio, ctx: _PipelineCtx) -> bool:
        ctx.frontmost = self.context.frontmost()
        ctx.preset = self.context.preset_for(ctx.frontmost)
        ctx.selection = self.context.read_selection(frontmost=ctx.frontmost)

        project = ctx.frontmost.get("project")
        if not project:
            pp = ctx.frontmost.get("project_path")
            project = Path(pp).name if pp else None
        ctx.vocab = load_vocab(self.config, ctx.preset, project)
        # Apple's SFSpeechRecognizer ignores initial_prompt — skip the work.
        if self.asr.backend == "apple" or not bool(
            self.config.get("asr.initial_prompt_from_vocab", True)
        ):
            initial_prompt = None
        else:
            initial_prompt = as_initial_prompt(ctx.vocab)

        self.hud.show_state("cleaning")
        self.menubar.set_state("cleaning")
        asr_t0 = time.monotonic()
        result = self.asr.transcribe_final(audio, initial_prompt=initial_prompt)
        ctx.metrics["asr_ms"] = int((time.monotonic() - asr_t0) * 1000)
        ctx.metrics["confidence"] = result.get("confidence")
        ctx.metrics["preset"] = ctx.preset
        ctx.metrics["app_bundle"] = ctx.frontmost.get("bundle_id")
        ctx.raw = (result.get("text") or "").strip()
        active_rules = self._rules_for_preset(ctx.preset)
        if active_rules:
            replaced = apply_replacements(ctx.raw, active_rules)
            if replaced != ctx.raw:
                ctx.metrics["replacements_applied"] = True
                ctx.raw = replaced

        if not ctx.raw:
            log.info("ASR produced empty transcript")
            self.hud.hide()
            return False
        if not self.asr.meets_confidence(result):
            log.info("Low confidence transcript; suppressing. length=%d chars", len(ctx.raw))
            self.hud.show_partial("low confidence — retry?")
            time.sleep(_LOW_CONFIDENCE_HUD_MS)
            self.hud.hide()
            return False
        return True

    def _phase_redact(self, ctx: _PipelineCtx) -> None:
        try:
            active_spec = self.config.active_backend
        except KeyError:
            active_spec = None
        if active_spec and active_spec.redact:
            ctx.raw, ctx.redactions = self.redactor.redact(ctx.raw)
        ctx.metrics["redactions"] = [r.get("name") for r in ctx.redactions]

    def _maybe_smart_punctuate(self, text: str) -> str:
        if not bool(self.config.get("cleanup.smart_punctuate", True)):
            return text
        try:
            return smart_punctuate(
                text,
                strip_fillers=bool(self.config.get("cleanup.strip_fillers", False)),
            )
        except Exception:
            log.exception("smart_punctuate failed; returning raw text")
            return text

    def _phase_cleanup(self, ctx: _PipelineCtx) -> None:
        if not bool(self.config.get("cleanup.enabled", True)):
            ctx.cleaned = self._maybe_smart_punctuate(ctx.raw)
            ctx.metrics["cleanup_skipped"] = "disabled"
            return

        # Fast path: short, well-formed transcripts ("open terminal", "yes",
        # "send it") don't benefit from LLM polish. Skipping cleanup here is the
        # single biggest perceived-latency win — saves 1–3 s for the common case.
        skip_under = int(self.config.get("cleanup.skip_if_under_chars", 80))
        if skip_under > 0 and len(ctx.raw.strip()) < skip_under:
            ctx.cleaned = self._maybe_smart_punctuate(ctx.raw)
            ctx.metrics["cleanup_skipped"] = f"short<{skip_under}"
            return

        few_shot = None
        if bool(self.config.get("learn.enabled", True)) and bool(
            self.config.get("cleanup.inject_few_shot", True)
        ):
            n = int(self.config.get("cleanup.few_shot_count", 4))
            few_shot = self.learn.recent_corrections(ctx.preset, n)

        t0 = time.monotonic()
        cleaned, cln_metrics = self.cleanup.clean_sync(
            ctx.raw,
            preset=ctx.preset,
            vocab=ctx.vocab,
            selection=ctx.selection,
            few_shot=few_shot,
        )
        ctx.metrics["cleanup_ms"] = int((time.monotonic() - t0) * 1000)
        ctx.metrics.update({f"cleanup_{k}": v for k, v in (cln_metrics or {}).items()})
        ctx.cleaned = (cleaned or ctx.raw).strip() or ctx.raw

    def _phase_paste(self, ctx: _PipelineCtx) -> None:
        self.hud.show_state("pasting")
        self.menubar.set_state("pasting")
        t0 = time.monotonic()
        ok = self.typer.paste(ctx.cleaned)
        if ok:
            self._remember_inserted(ctx.cleaned)
        ctx.metrics["paste_ms"] = int((time.monotonic() - t0) * 1000)
        ctx.metrics["paste_ok"] = ok

    def _phase_persist(self, ctx: _PipelineCtx) -> None:
        if not bool(self.config.get("history.enabled", True)):
            return

        bundle_id = ctx.frontmost.get("bundle_id")
        incognito = self.config.get("history.incognito_apps") or []
        if bundle_id and isinstance(incognito, list) and bundle_id in incognito:
            log.info("history skipped (incognito app: %s)", bundle_id)
            ctx.metrics["history_skipped"] = "incognito"
            self._last_transcript = None
            log_metrics(log, "utterance", **ctx.metrics)
            return

        entry: dict = {
            "type": "utterance",
            "preset": ctx.preset,
            "duration_ms": ctx.metrics.get("duration_ms"),
            "metrics": ctx.metrics,
        }
        if bool(self.config.get("history.store_app_bundle", True)):
            entry["app_bundle"] = bundle_id
        if bool(self.config.get("history.store_raw", True)):
            entry["raw"] = ctx.raw
        if bool(self.config.get("history.store_cleaned", True)):
            entry["cleaned"] = ctx.cleaned
        if bool(self.config.get("history.store_selection", False)):
            selection = getattr(ctx, "selection", None)
            if selection:
                entry["selection"] = selection
        history_append(self.config, entry)
        self._last_transcript = entry

        if bool(self.config.get("learn.enabled", True)):
            try:
                self.learn.arm(ctx.raw, ctx.cleaned)
            except Exception as e:
                log.warning("Learn watcher failed to arm: %s", e)

        log_metrics(log, "utterance", **ctx.metrics)

    def _handle_command(self, command, ctx: _PipelineCtx) -> None:
        action = command.action
        log.info("Voice command: %s", command.name)
        ctx.metrics["command"] = command.name
        try:
            if action == "insert":
                text = command.text or ""
                if self.typer.paste(text):
                    self._remember_inserted(text)
            elif action == "scratch_last":
                backspace = getattr(self.typer, "backspace", None)
                if callable(backspace):
                    backspace(command.count or 0)
            elif action == "discard":
                pass
            elif action == "stop":
                self.recorder.cancel()
            elif action == "paste_raw":
                if self.typer.paste(ctx.raw):
                    self._remember_inserted(ctx.raw)
            elif action == "redo_last":
                if self._last_transcript:
                    last_raw = self._last_transcript.get("raw", "")
                    preset = self._last_transcript.get("preset", "default")
                    vocab = load_vocab(self.config, preset)
                    cleaned, _ = self.cleanup.clean_sync(last_raw, preset=preset, vocab=vocab)
                    text = cleaned or last_raw
                    if self.typer.paste(text):
                        self._remember_inserted(text)
            history_append(
                self.config,
                {
                    "type": "command",
                    "command": command.name,
                    "raw": ctx.raw,
                    "app_bundle": ctx.frontmost.get("bundle_id"),
                },
            )
        except Exception as e:
            log.exception("Command handling failed: %s", e)


def run_app(startup_urls: list[str] | None = None) -> None:
    app = App()
    app.boot()
    _maybe_start_webui(app)
    _maybe_schedule_auto_purge(app)
    for startup_url in startup_urls or []:
        url_scheme.dispatch(startup_url, app)

    def _sig(_signum, _frame):
        app.shutdown()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    # rumps blocks the main thread running the NSApplication runloop.
    # The CGEventTap was added to the main CFRunLoop in hotkey.start(), so it runs alongside.
    app.menubar.run()


def _maybe_start_webui(app: App) -> None:
    cfg = getattr(app, "config", None)
    if cfg is None:
        return
    if not bool(cfg.get("webui.autostart", True)):
        return
    host = cfg.get("webui.host", "127.0.0.1") or "127.0.0.1"
    port = int(cfg.get("webui.port", 47843) or 47843)
    try:
        from dictate.webui.server import start_in_background

        start_in_background(cfg, host=host, port=port)
    except Exception:  # noqa: BLE001
        log.exception("failed to autostart WebUI")
        return
    if cfg.get("webui.open_on_start", False):
        import subprocess

        try:
            subprocess.Popen(["open", f"http://{host}:{port}"], close_fds=True)
        except OSError:
            pass


def _maybe_schedule_auto_purge(app: App) -> None:
    cfg = getattr(app, "config", None)
    if cfg is None:
        return
    days = int(cfg.get("history.auto_purge_days", 0) or 0)
    if days <= 0:
        return

    from dictate.history import purge_older_than

    def _run_purge() -> None:
        try:
            purge_older_than(cfg, days)
        except Exception:
            log.exception("auto-purge failed")

    if bool(cfg.get("history.auto_purge_on_start", True)):
        threading.Thread(target=_run_purge, name="history-purge-startup", daemon=True).start()

    def _periodic() -> None:
        while True:
            time.sleep(24 * 3600)
            _run_purge()

    threading.Thread(target=_periodic, name="history-purge-daily", daemon=True).start()
