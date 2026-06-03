from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import APIRouter, Body, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from dictate import config as config_module
from dictate.config import Config
from dictate.logging_setup import get_logger
from dictate.webui.store import HistoryStore

log = get_logger(__name__)

SECRET_KEY_RE = re.compile(r"key|token|secret|password", re.IGNORECASE)
PERMISSION_LABELS = {
    "accessibility": "Accessibility",
    "microphone": "Microphone",
    "input_monitoring": "Input Monitoring",
}

# Whitelisted preference keys editable via the WebUI. Each entry: (key, type, label, group).
# Anything outside this list MUST be edited in settings.yaml directly.
EDITABLE_PREFS: list[tuple[str, str, str, str]] = [
    ("webui.autostart", "bool", "Start WebUI with dictate", "WebUI"),
    ("webui.open_on_start", "bool", "Open browser on autostart", "WebUI"),
    (
        "cleanup.enabled",
        "bool",
        "Enable LLM cleanup (off = use raw dictation + smart punctuation)",
        "Cleanup",
    ),
    ("cleanup.backend", "enum:ollama,openrouter", "Cleanup backend (when enabled)", "Cleanup"),
    ("cleanup.model", "string", "Cleanup model", "Cleanup"),
    ("cleanup.code_grammar.enabled", "bool", "Code grammar mode", "Cleanup"),
    ("cleanup.smart_punctuate", "bool", "Smart punctuation when LLM skipped", "Cleanup"),
    ("learn.enabled", "bool", "Correction learning", "Pipeline"),
    ("health.enabled", "bool", "Backend health checks", "Pipeline"),
    ("typer.refuse_on_secure_input", "bool", "Refuse to type into secure fields", "Typer"),
    ("logging.level", "enum:DEBUG,INFO,WARNING,ERROR", "Log level", "Logging"),
    # Privacy
    ("history.enabled", "bool", "Persist history at all", "Privacy"),
    ("history.store_raw", "bool", "Store raw ASR transcript", "Privacy"),
    ("history.store_cleaned", "bool", "Store cleaned transcript", "Privacy"),
    ("history.store_app_bundle", "bool", "Store frontmost app id", "Privacy"),
    ("history.store_selection", "bool", "Store selection context", "Privacy"),
    ("history.auto_purge_days", "int", "Auto-purge entries older than (days, 0 = off)", "Privacy"),
    ("history.auto_purge_on_start", "bool", "Run auto-purge at startup", "Privacy"),
]


class PrefUpdate(BaseModel):
    key: str
    value: Any


class PurgeRequest(BaseModel):
    # ``older_than_days=0`` would mean "every entry with a parseable timestamp"
    # — never the intended semantics. The CLI/auto-purge path in
    # ``dictate.history.purge_older_than`` early-returns on ``days <= 0`` and
    # the HTML form is bounded by ``min="1"``; align the API contract with
    # both so a typo or intercepted request cannot wipe the whole history.
    older_than_days: int = Field(ge=1, le=36500)


def create_router(store: HistoryStore, templates_dir: Path, config: Config) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=str(templates_dir))

    def page_context(**values: object) -> dict[str, object]:
        total_entries = store.count()
        last_updated = store.last_updated()
        return {
            "total_entries": total_entries,
            "entry_label": "entry" if total_entries == 1 else "entries",
            "last_updated_label": last_updated.strftime("%Y-%m-%d %H:%M")
            if last_updated
            else "never",
            **values,
        }

    @router.get("/", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            page_context(title="Dashboard"),
        )

    @router.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            page_context(title="History", entries=store.list(limit=1)),
        )

    @router.get("/api/dashboard")
    async def dashboard_data() -> dict[str, Any]:
        stats = store.stats()
        # Last 7 day-counts for the sparkline (oldest → newest).
        by_day = stats.get("by_day", {})
        last_7 = list(by_day.items())[-7:]
        health = _dashboard_health(config)
        return {
            "today": store.today_summary(),
            "recent": [entry.model_dump(mode="json") for entry in store.recent(limit=8)],
            "health": health,
            "totals": {
                "entries": store.count(),
                "last_updated": store.last_updated().isoformat() if store.last_updated() else None,
            },
            "sparkline_7d": [{"day": d, "count": c} for d, c in last_7],
            "hotkey": _hotkey_label(config),
            "suggestions": _dashboard_suggestions(config, health, stats),
        }

    @router.get("/entry/{id}", response_class=HTMLResponse)
    async def detail(request: Request, id: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "detail.html", page_context(title="Entry", entry_id=id)
        )

    @router.get("/stats", response_class=HTMLResponse)
    async def stats_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "stats.html", page_context(title="Stats"))

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        load_failed, load_error = config_module.was_load_failure()
        settings_path = (
            (config.root / "config" / "settings.yaml").expanduser().resolve(strict=False)
        )
        settings_yaml = yaml.safe_dump(
            _redact_secrets(config.settings), sort_keys=False, allow_unicode=True
        )
        return templates.TemplateResponse(
            request,
            "settings.html",
            page_context(
                title="Settings",
                load_failed=load_failed,
                load_error=load_error,
                permissions=_permissions_status(),
                settings_path=str(settings_path),
                settings_yaml_lines=_tokenize_yaml(settings_yaml),
                editable_prefs=_editable_pref_values(config),
                prefs_path=str(config.prefs_path),
                replacements_summary=_replacements_summary(config),
            ),
        )

    @router.get("/api/replacements")
    async def replacements_api() -> dict[str, Any]:
        return _replacements_summary(config)

    @router.post("/api/settings/pref")
    async def update_pref(payload: PrefUpdate) -> dict[str, Any]:
        spec = next((p for p in EDITABLE_PREFS if p[0] == payload.key), None)
        if spec is None:
            raise HTTPException(status_code=400, detail=f"key not editable: {payload.key}")
        _key, kind, _label, _group = spec
        value = _coerce_pref_value(kind, payload.value)
        try:
            config.persist_pref(payload.key, value)
        except Exception as exc:  # noqa: BLE001
            log.exception("webui: persist_pref failed for key=%s", payload.key)
            raise HTTPException(status_code=500, detail="persist failed") from exc
        return {"key": payload.key, "value": value, "prefs_path": str(config.prefs_path)}

    @router.get("/api/transcripts")
    async def transcripts(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        q: str | None = None,
        preset: str | None = None,
        app: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        since_dt = _parse_since(since)
        return [
            entry.model_dump(mode="json")
            for entry in store.list(
                limit=limit, offset=offset, q=q, preset=preset, app=app, since=since_dt
            )
        ]

    @router.get("/api/transcripts/{id}")
    async def transcript(id: str) -> dict:
        entry = store.get(id)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entry not found")
        prev_id, next_id = store.neighbors(id)
        payload = entry.model_dump(mode="json")
        payload["_neighbors"] = {"prev": prev_id, "next": next_id}
        return payload

    @router.delete("/api/transcripts/{id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_transcript(id: str) -> Response:
        if store.delete([id]) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entry not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/api/stats")
    async def stats() -> dict:
        return store.stats()

    @router.get("/api/export")
    async def export(format: Literal["jsonl", "csv", "markdown"] = "jsonl") -> Response:
        payload = store.export(format)
        media_types = {
            "jsonl": "application/x-ndjson; charset=utf-8",
            "csv": "text/csv; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
        }
        extensions = {"jsonl": "jsonl", "csv": "csv", "markdown": "md"}
        headers = {
            "Content-Disposition": f'attachment; filename="dictate-history.{extensions[format]}"'
        }
        if isinstance(payload, bytes):
            return Response(payload, media_type=media_types[format], headers=headers)
        return PlainTextResponse(payload, media_type=media_types[format], headers=headers)

    @router.post("/api/purge")
    async def purge(body: Annotated[PurgeRequest, Body()]) -> dict[str, int]:
        return {"deleted": store.purge_older_than(body.older_than_days)}

    return router


def _dashboard_health(config: Config) -> dict[str, Any]:
    import time
    from urllib.parse import urlparse

    import httpx

    cleanup_enabled = bool(config.get("cleanup.enabled", False))
    backend_name = str(config.get("cleanup.backend", "ollama"))
    out: dict[str, Any] = {
        "cleanup_enabled": cleanup_enabled,
        "active_backend": backend_name if cleanup_enabled else "raw",
        "configured_model": config.get("cleanup.model") if cleanup_enabled else None,
        "resolved_model": None,
        "backend": {"name": backend_name, "ok": True, "latency_ms": None, "error": None},
        "permissions": _permissions_status() or [],
    }

    if not cleanup_enabled:
        out["backend"]["note"] = "LLM cleanup disabled — raw + smart punctuation"
        return out

    try:
        spec = config.backend(backend_name)
        url = spec.health_url
        host = urlparse(url).hostname or ""
        out["backend"]["ok"] = False
        out["backend"]["url"] = url
        out["backend"]["host"] = host
        t0 = time.monotonic()
        with httpx.Client(timeout=2.5, verify=True) as client:
            resp = client.get(url, headers=spec.auth_headers())
        out["backend"]["latency_ms"] = int((time.monotonic() - t0) * 1000)
        out["backend"]["ok"] = resp.is_success
        if not resp.is_success:
            out["backend"]["error"] = f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        log.warning("webui: dashboard backend probe failed: %s", type(exc).__name__)
        out["backend"]["error"] = "probe failed"
        spec = None

    try:
        from dictate.cleanup import CleanupClient

        base_url = getattr(spec, "base_url", None) if spec else None
        installed = CleanupClient._list_ollama_models(base_url) if base_url else []
        if installed:
            out["resolved_model"] = CleanupClient._pick_best_ollama_model(
                installed, str(config.get("cleanup.model") or "")
            )
            out["installed_models"] = installed
    except Exception:  # noqa: BLE001
        pass

    return out


def _hotkey_label(config: Config) -> str:
    mods = config.get("hotkey.mods", ["cmd"]) or ["cmd"]
    key = str(config.get("hotkey.key", "h")).upper()
    symbols = {"cmd": "⌘", "shift": "⇧", "option": "⌥", "control": "⌃"}
    return "".join(symbols.get(str(m).lower(), str(m).upper()) for m in mods) + key


def _dashboard_suggestions(
    config: Config, health: dict[str, Any], stats: dict[str, Any]
) -> list[dict[str, str]]:
    """Surface actionable hints based on current configuration and runtime state.

    Each suggestion: {kind: info|warn, title, detail, action_label, action_href}.
    Kept short — at most three so the panel never becomes noise.
    """
    out: list[dict[str, str]] = []

    backend = health.get("backend") or {}
    if not backend.get("ok"):
        out.append(
            {
                "kind": "warn",
                "title": "Cleanup backend unreachable",
                "detail": backend.get("error") or "Backend did not respond.",
                "action_label": "Open settings",
                "action_href": "/settings",
            }
        )

    perms = health.get("permissions") or []
    missing = [p for p in perms if isinstance(p, dict) and not p.get("granted")]
    if missing:
        labels = ", ".join(str(p.get("label")) for p in missing)
        out.append(
            {
                "kind": "warn",
                "title": "Missing macOS permissions",
                "detail": f"Not granted yet: {labels}. Dictate needs these to record and paste.",
                "action_label": "Grant in Settings",
                "action_href": "/settings",
            }
        )

    purge_days = int(config.get("history.auto_purge_days", 0) or 0)
    if purge_days == 0 and stats.get("total", 0) > 50:
        out.append(
            {
                "kind": "info",
                "title": "Auto-purge is off",
                "detail": (
                    "You have a growing history with no retention limit. "
                    "Set a purge window so old transcripts roll off automatically."
                ),
                "action_label": "Set retention",
                "action_href": "/settings",
            }
        )

    return out[:3]


def _redact_secrets(value: Any, key: str | None = None) -> Any:
    if key and SECRET_KEY_RE.search(key):
        return "***"
    if isinstance(value, Mapping):
        return {str(k): _redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _tokenize_yaml(yaml_text: str) -> list[list[tuple[str, str]]]:
    lines: list[list[tuple[str, str]]] = []
    for line in yaml_text.splitlines():
        match = re.match(r"^(\s*)([^:\n][^:\n]*?)(:)(.*)$", line)
        if match and not match.group(2).lstrip().startswith("-"):
            indent, key, colon, rest = match.groups()
            lines.append(
                [
                    ("", indent),
                    ("yaml-key", key),
                    ("yaml-punctuation", colon),
                    ("", rest),
                ]
            )
        else:
            lines.append([("", line)])
    return lines


def _permissions_status() -> list[dict[str, object]] | None:
    try:
        from dictate import permissions
    except ImportError:
        return None

    check_all = getattr(permissions, "check_all", None)
    if not callable(check_all):
        return None

    try:
        raw_status = check_all()
    except Exception:
        return None

    if not isinstance(raw_status, Mapping):
        return None

    return [
        {"label": label, "granted": bool(raw_status.get(key))}
        for key, label in PERMISSION_LABELS.items()
    ]


def _editable_pref_values(config: Config) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key, kind, label, group in EDITABLE_PREFS:
        result.append(
            {
                "key": key,
                "kind": kind,
                "label": label,
                "group": group,
                "value": config.get(key),
                "choices": kind.split(":", 1)[1].split(",") if kind.startswith("enum:") else None,
            }
        )
    return result


def _replacements_summary(config: Config) -> dict[str, Any]:
    """Inspect the configured replacement files and return a compact summary
    for the WebUI. Read-only; users edit the YAML and reload dictate."""
    from dictate.replacements import load as load_replacements

    root = config.root
    candidates = [
        root / "config" / "vocab" / "replacements.txt",
        root / "config" / "vocab" / "replacements.yaml",
    ]
    preset_glob = sorted((root / "config" / "vocab").glob("*.replacements.yaml"))
    files: list[dict[str, Any]] = []
    rules_preview: list[dict[str, Any]] = []
    for path in candidates + list(preset_glob):
        exists = path.exists()
        rules = load_replacements(path) if exists else []
        files.append(
            {
                "path": str(path),
                "exists": exists,
                "rule_count": len(rules),
                "preset": path.name.split(".", 1)[0]
                if path.name.endswith(".replacements.yaml")
                else None,
            }
        )
        for rule in rules[:50]:
            rules_preview.append(
                {
                    "pattern": rule.pattern,
                    "replacement": rule.replacement,
                    "regex": rule.regex,
                    "case_sensitive": rule.case_sensitive,
                    "source": rule.source,
                }
            )
    return {"files": files, "rules": rules_preview, "total": len(rules_preview)}


def _coerce_pref_value(kind: str, value: Any) -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if kind.startswith("enum:"):
        choices = kind.split(":", 1)[1].split(",")
        sval = str(value)
        if sval not in choices:
            raise HTTPException(status_code=400, detail=f"value must be one of {choices}")
        return sval
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return value


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.isdigit():
        return datetime.now(UTC) - timedelta(days=int(value))
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid since"
        ) from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
