from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dictate.logging_setup import get_logger

log = get_logger(__name__)
DEFAULT_ROOT = Path(os.path.expanduser("~/dictate"))
config_load_failed: bool = False
config_load_error: str | None = None


def _expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(p))


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Recursively merge overlay into base (in place). Overlay wins on conflicts."""
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _minimal_defaults(root: Path) -> dict[str, Any]:
    return {
        "settings": {
            "cleanup": {
                "enabled": True,
                "backend": "ollama",
                "privacy_backend": "ollama",
                "model": "qwen2.5:3b-instruct",
                "stream": True,
                "timeout_seconds": 8,
                "fallback_chain": ["ollama", "raw"],
                "temperature": 0.2,
                "max_tokens": 800,
            },
            "history": {"path": str(root / "history.jsonl")},
            "logging": {"level": "INFO", "json": True, "file": str(root / "logs/dictate.log")},
            "asr": {"backend": "faster-whisper", "model": "small.en"},
            "vad": {"enabled": True},
            "hotkey": {"mods": ["cmd"], "key": "h", "mode": "auto"},
        },
        "backends_raw": {
            "ollama": {
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key_env": None,
                "default_model": "qwen2.5:3b-instruct",
                "redact": False,
                "health_path": "/models",
            }
        },
        "presets": {
            "default": {
                "system": "Clean up the dictated text. Preserve these terms verbatim: {vocab}"
            },
            "selection_suffix": "\n\nSELECTION:\n---\n{selection}\n---",
        },
        "commands": [],
        "app_map": {},
        "redact_patterns": [],
    }


def was_load_failure() -> tuple[bool, str | None]:
    return config_load_failed, config_load_error


@dataclass
class BackendSpec:
    name: str
    base_url: str
    api_key_env: str | None
    default_model: str
    redact: bool
    health_path: str = "/models"

    def __post_init__(self) -> None:
        from dictate.safety import validate_backend_url

        validate_backend_url(self.base_url)

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)

    @property
    def requires_api_key(self) -> bool:
        return bool(self.api_key_env)

    @property
    def has_api_key(self) -> bool:
        return not self.requires_api_key or bool(self.api_key)

    def ensure_api_key(self) -> None:
        if self.requires_api_key and not self.api_key:
            raise ValueError(f"backend '{self.name}' requires env var {self.api_key_env} (not set)")

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}{self.health_path}"


@dataclass
class Config:
    root: Path
    settings: dict[str, Any] = field(default_factory=dict)
    backends_raw: dict[str, dict[str, Any]] = field(default_factory=dict)
    presets: dict[str, Any] = field(default_factory=dict)
    commands: list[dict[str, Any]] = field(default_factory=list)
    app_map: dict[str, str] = field(default_factory=dict)
    redact_patterns: list[dict[str, str]] = field(default_factory=list)

    # ---------- convenience accessors ----------
    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.settings
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value: Any) -> None:
        """In-memory override for a dotted key. Does NOT persist to settings.yaml.

        Used for runtime toggles (e.g. Fast Mode) that should reset on restart.
        Call ``persist_pref(dotted, value)`` to persist instead.
        """
        cur: Any = self.settings
        parts = dotted.split(".")
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    # ---------- user prefs (persisted overlay) ----------
    @property
    def prefs_path(self) -> Path:
        return self.root / "user_prefs.yaml"

    def persist_pref(self, dotted: str, value: Any) -> None:
        """Update the in-memory value AND persist to ``user_prefs.yaml``.

        user_prefs.yaml is a thin user-writable overlay on top of settings.yaml.
        It survives restarts; settings.yaml stays as shipped defaults.
        """
        self.set(dotted, value)
        path = self.prefs_path
        existing: dict[str, Any] = {}
        if path.exists():
            loaded = _load_yaml(path)
            if isinstance(loaded, dict):
                existing = loaded
        cur: Any = existing
        parts = dotted.split(".")
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, sort_keys=False)

    def backend(self, name: str) -> BackendSpec:
        raw = self.backends_raw.get(name)
        if not raw:
            raise KeyError(f"backend '{name}' not configured in backends.yaml")
        return BackendSpec(
            name=name,
            base_url=raw["base_url"].rstrip("/"),
            api_key_env=raw.get("api_key_env"),
            default_model=raw.get("default_model", ""),
            redact=bool(raw.get("redact", False)),
            health_path=raw.get("health_path", "/models"),
        )

    @property
    def active_backend(self) -> BackendSpec:
        return self.backend(self.default_backend_name)

    @property
    def default_backend_name(self) -> str:
        return str(self.get("cleanup.backend", "ollama"))

    @property
    def privacy_backend_name(self) -> str:
        return str(self.get("cleanup.privacy_backend", "ollama"))

    @property
    def fallback_chain(self) -> list[str]:
        return list(self.get("cleanup.fallback_chain", ["ollama", "raw"]))

    @property
    def log_path(self) -> str:
        return _expand(str(self.get("logging.file", str(self.root / "logs/dictate.log"))))

    @property
    def history_path(self) -> str:
        return _expand(str(self.get("history.path", str(self.root / "history.jsonl"))))

    @property
    def models_dir(self) -> Path:
        return Path(_expand(str(self.get("models.dir", str(self.root / "models")))))

    @property
    def onboarded_marker(self) -> Path:
        return self.root / ".onboarded"

    @property
    def project_search_roots(self) -> list[Path]:
        configured = self.get("context.project_search_roots")
        if isinstance(configured, list) and configured:
            return [Path(_expand(str(p))) for p in configured]
        return [Path.home() / d for d in ("Developer", "Projects", "code", "src")]

    def preset(self, name: str) -> dict[str, Any]:
        return self.presets.get(name) or self.presets.get("default") or {}

    def preset_for_bundle(self, bundle_id: str | None) -> str:
        if bundle_id and bundle_id in self.app_map:
            return self.app_map[bundle_id]
        return "default"

    # ---------- loader ----------
    @classmethod
    def load(cls, root: Path | None = None) -> Config:
        global config_load_error, config_load_failed
        if root is None:
            env_root = os.environ.get("DICTATE_ROOT")
            root = Path(env_root) if env_root else DEFAULT_ROOT
        root = Path(root)
        cfg_dir = root / "config"
        c = cls(root=root)
        config_load_failed = False
        config_load_error = None
        current_path: Path | None = None
        try:
            current_path = cfg_dir / "settings.yaml"
            c.settings = _load_yaml(current_path) or {}
            current_path = cfg_dir / "backends.yaml"
            c.backends_raw = _load_yaml(current_path) or {}
            current_path = cfg_dir / "presets.yaml"
            c.presets = _load_yaml(current_path) or {}
            current_path = cfg_dir / "commands.yaml"
            c.commands = _load_yaml(current_path) or []
            current_path = cfg_dir / "app_map.yaml"
            c.app_map = _load_yaml(current_path) or {}
            current_path = cfg_dir / "redact.yaml"
            c.redact_patterns = _load_yaml(current_path) or []
            current_path = c.prefs_path
            prefs = _load_yaml(current_path)
            if isinstance(prefs, dict):
                _deep_merge(c.settings, prefs)
            return c
        except Exception as exc:
            config_load_failed = True
            path_text = str(current_path or cfg_dir)
            config_load_error = f"{path_text}: {type(exc).__name__}: {exc}"
            log.error("config load failed for %s: %s", path_text, exc, exc_info=True)
            defaults = _minimal_defaults(root)
            c.settings = defaults["settings"]
            c.backends_raw = defaults["backends_raw"]
            c.presets = defaults["presets"]
            c.commands = defaults["commands"]
            c.app_map = defaults["app_map"]
            c.redact_patterns = defaults["redact_patterns"]
            return c


def load_config(root: Path | None = None) -> Config:
    return Config.load(root)
