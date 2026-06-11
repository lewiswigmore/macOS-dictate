from __future__ import annotations

import glob
import importlib.metadata
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from dictate import conflicts
from dictate.config import Config, load_config
from dictate.health import HealthMonitor
from dictate.permissions import Permissions

OK = "✓"
PROBLEM = "✗"
SKIP = "-"
UNKNOWN = "?"


@dataclass(frozen=True)
class CheckLine:
    marker: str
    label: str
    detail: str

    @property
    def is_problem(self) -> bool:
        return self.marker == PROBLEM


def _version() -> str:
    try:
        return importlib.metadata.version("dictate")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _print(out: TextIO, line: str = "") -> None:
    print(line, file=out)


def _format_value(label: str, value: str, width: int = 17) -> str:
    return f"  {label + ':':<{width}} {value}"


def _format_check(line: CheckLine, width: int = 20) -> str:
    return f"  {line.marker} {line.label + ':':<{width}} {line.detail}"


def _conflict_marker(severity: conflicts.Severity) -> str:
    return {"info": "ℹ", "warning": "⚠", "error": PROBLEM}[severity]


def _safe(label: str, fn) -> CheckLine:  # noqa: ANN001
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return CheckLine(UNKNOWN, label, str(exc))


def _permission_lines() -> list[CheckLine]:
    if os.environ.get("DICTATE_DOCTOR_SKIP_SLOW_CHECKS"):
        return [
            CheckLine(UNKNOWN, "Accessibility", "skipped"),
            CheckLine(UNKNOWN, "Microphone", "skipped"),
            CheckLine(UNKNOWN, "Input Monitoring", "skipped"),
        ]
    perms = Permissions()
    settings = {
        "Accessibility": "open System Settings → Privacy & Security → Accessibility",
        "Microphone": "open System Settings → Privacy & Security → Microphone",
        "Input Monitoring": "open System Settings → Privacy & Security → Input Monitoring",
    }
    checks = {
        "Accessibility": perms.check_accessibility,
        "Microphone": perms.check_microphone,
        "Input Monitoring": perms.check_input_monitoring,
    }
    lines: list[CheckLine] = []
    for label, fn in checks.items():

        def run_check(label: str = label, fn=fn) -> CheckLine:  # noqa: ANN001
            granted = fn()
            if granted is True:
                return CheckLine(OK, label, "granted")
            if granted is False:
                return CheckLine(PROBLEM, label, f"denied  → {settings[label]}")
            return CheckLine(UNKNOWN, label, "unknown")

        lines.append(_safe(label, run_check))
    return lines


def _audio_lines() -> tuple[list[str], list[CheckLine]]:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except Exception as exc:  # noqa: BLE001
        return [
            _format_value("Default input", "unavailable in this environment"),
            _format_value("Available inputs", f"unavailable in this environment ({exc})"),
        ], []

    try:
        default = AVCaptureDevice.defaultDeviceWithMediaType_(AVMediaTypeAudio)
        devices = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeAudio) or [])
        default_name = str(default.localizedName()) if default is not None else "unknown"
        names = [str(device.localizedName()) for device in devices]
        lines = [
            _format_value("Default input", default_name),
            _format_value("Available inputs", f"{len(names)} device(s)"),
        ]
        lines.extend(f"    - {name}" for name in names)
        return lines, []
    except Exception as exc:  # noqa: BLE001
        return [_format_value("Default input", f"unavailable ({exc})")], []


def _ollama_models(config: Config, backend_name: str) -> str | None:
    try:
        import httpx

        backend = config.backend(backend_name)
        with httpx.Client(timeout=3.0) as client:
            response = client.get(backend.health_url, headers=backend.auth_headers())
        if not response.is_success:
            return None
        data = response.json()
        raw_models = data.get("data") or data.get("models") or []
        names: list[str] = []
        if isinstance(raw_models, list):
            for item in raw_models:
                if isinstance(item, dict):
                    name = item.get("id") or item.get("name") or item.get("model")
                    if name:
                        names.append(str(name))
        return ", ".join(names[:5]) if names else None
    except Exception:  # noqa: BLE001
        return None


def _backend_lines(config: Config) -> list[CheckLine]:
    if os.environ.get("DICTATE_DOCTOR_SKIP_SLOW_CHECKS"):
        return [CheckLine(SKIP, name, "skipped") for name in config.backends_raw]
    monitor = HealthMonitor(config)
    lines: list[CheckLine] = []
    for name in config.backends_raw:

        def check(name: str = name) -> CheckLine:
            backend = config.backend(name)
            label = f"{name} ({backend.base_url})"
            if not backend.has_api_key:
                env = backend.api_key_env or "API key"
                return CheckLine(SKIP, name, f"not configured (set {env})")
            reachable = monitor.ping_once(name)
            if reachable:
                models = _ollama_models(config, name)
                detail = "reachable" if not models else f"reachable, models: {models}"
                return CheckLine(OK, label, detail)
            status = monitor.status.get(name, {})
            err = status.get("error") or "unreachable"
            return CheckLine(PROBLEM, label, str(err))

        lines.append(_safe(name, check))
    return lines


def _has_hf_snapshot(model: str, cache_dir: Path) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(model, cache_dir=str(cache_dir), local_files_only=True)  # nosec B615 - local_files_only=True forbids any network fetch; this is a cache probe.
        return True
    except Exception:  # noqa: BLE001
        return False


def _whisper_repo(model: str) -> str:
    """Resolve a faster-whisper model name to its Hugging Face repo id.

    Distil models live under ``Systran/faster-distil-whisper-*`` rather than
    ``Systran/faster-whisper-*``, so use faster-whisper's own mapping when
    available and fall back to the plain naming otherwise.
    """
    try:
        from faster_whisper.utils import _MODELS

        repo = _MODELS.get(model)
        if repo:
            return repo
    except Exception:  # noqa: BLE001
        pass
    return f"Systran/faster-whisper-{model}"


def _model_lines(config: Config) -> list[CheckLine]:
    if os.environ.get("DICTATE_DOCTOR_SKIP_SLOW_CHECKS"):
        return [
            CheckLine(UNKNOWN, "Whisper", "skipped"),
            CheckLine(UNKNOWN, "Silero VAD", "skipped"),
        ]
    lines: list[CheckLine] = []
    whisper_model = str(config.get("asr.model", "distil-medium.en"))
    whisper_dir = config.models_dir / "whisper"
    whisper_present = any(whisper_dir.glob(f"**/*{whisper_model}*"))
    if not whisper_present:
        repo = _whisper_repo(whisper_model)
        whisper_present = _has_hf_snapshot(repo, whisper_dir)
    detail = whisper_model if not whisper_present else f"{whisper_model} (present)"
    lines.append(CheckLine(OK if whisper_present else PROBLEM, "Whisper", detail))

    vad_path = config.models_dir / "silero_vad.onnx"
    lines.append(
        CheckLine(
            OK if vad_path.exists() else PROBLEM,
            "Silero VAD",
            "present" if vad_path.exists() else "missing",
        )
    )
    return lines


def _history_count(config: Config) -> int:
    path = Path(config.history_path)
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _recent_errors(config: Config) -> list[str]:
    log_dir = Path(config.log_path).parent
    entries: list[tuple[float, str]] = []
    for name in glob.glob(str(log_dir / "*.log")):
        path = Path(name)
        try:
            mtime = path.stat().st_mtime
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-500:]:
            if "ERROR" in line or '"level":"ERROR"' in line or '"level": "ERROR"' in line:
                entries.append((mtime, line.strip()))
    entries.sort(key=lambda item: item[0])
    return [line for _, line in entries[-5:]]


def _config_file_label(config: Config) -> str:
    settings_path = config.root / "config" / "settings.yaml"
    return str(settings_path) if settings_path.exists() else "defaults"


def run(out: TextIO | None = None) -> int:
    out = out or sys.stdout
    problem = False

    _print(out, "dictate doctor")
    _print(out, "==============")
    _print(out)

    _print(out, "System")
    mac_version, _, mac_machine = platform.mac_ver()
    _print(
        out,
        _format_value(
            "macOS",
            f"{mac_version or 'unknown'} {f'({mac_machine})' if mac_machine else ''}".strip(),
        ),
    )
    _print(
        out,
        _format_value(
            "Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
    )
    _print(out, _format_value("Architecture", platform.machine() or "unknown"))
    _print(out, _format_value("dictate version", _version()))
    _print(out)

    _print(out, "Permissions")
    for line in _permission_lines():
        problem = problem or line.is_problem
        _print(out, _format_check(line))
    _print(out)

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001
        config = Config(root=Path(os.path.expanduser("~/dictate")))
        config_line = CheckLine(UNKNOWN, "Config", str(exc))
    else:
        config_line = CheckLine(OK, "Config", "loaded")

    _print(out, "Audio")
    for line in _audio_lines()[0]:
        _print(out, line)
    _print(out)

    _print(out, "Backends")
    if config.backends_raw:
        for line in _backend_lines(config):
            problem = problem or line.is_problem
            _print(out, _format_check(line, width=34))
    else:
        _print(out, _format_check(CheckLine(UNKNOWN, "Backends", "none configured"), width=34))
    _print(out)

    _print(out, "Models")
    for line in _model_lines(config):
        problem = problem or line.is_problem
        _print(out, _format_check(line, width=13))
    _print(out)

    _print(out, "Configuration")
    problem = problem or config_line.is_problem
    _print(out, _format_value("Config file", _config_file_label(config)))
    presets = ", ".join(name for name in config.presets if name != "default") or "none"
    _print(out, _format_value("Vocab presets", presets))
    try:
        history = str(_history_count(config))
    except Exception as exc:  # noqa: BLE001
        history = f"? {exc}"
    _print(out, _format_value("History entries", history))
    _print(out)

    _print(out, "Conflicts")
    found_conflicts = conflicts.check_all()
    if found_conflicts:
        for conflict in found_conflicts:
            problem = problem or conflict.severity == "error"
            _print(
                out, f"  {_conflict_marker(conflict.severity)} {conflict.name}: {conflict.detail}"
            )
            _print(out, f"    Suggestion: {conflict.suggestion}")
    else:
        _print(out, "  ✓ No known conflicts detected")
    _print(out)

    _print(out, "Recent errors (last 5 from logs/)")
    try:
        errors = _recent_errors(config)
    except Exception as exc:  # noqa: BLE001
        errors = [f"? {exc}"]
    if errors:
        for entry in errors:
            _print(out, f"  {entry}")
    else:
        _print(out, "  [none]")

    return 1 if problem else 0
