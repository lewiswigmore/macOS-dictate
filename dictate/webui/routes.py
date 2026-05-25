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
from markupsafe import Markup, escape
from pydantic import BaseModel, Field
from starlette.requests import Request

from dictate import config as config_module
from dictate.config import Config
from dictate.webui.store import HistoryStore

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
    ("cleanup.code_grammar.enabled", "bool", "Code grammar mode", "Cleanup"),
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
    older_than_days: int = Field(ge=0, le=36500)


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
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            page_context(title="History", entries=store.list(limit=1)),
        )

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
                settings_yaml_highlighted=_highlight_yaml(settings_yaml),
                editable_prefs=_editable_pref_values(config),
                prefs_path=str(config.prefs_path),
            ),
        )

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
            raise HTTPException(status_code=500, detail=f"persist failed: {exc}") from exc
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


def _redact_secrets(value: Any, key: str | None = None) -> Any:
    if key and SECRET_KEY_RE.search(key):
        return "***"
    if isinstance(value, Mapping):
        return {str(k): _redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _highlight_yaml(yaml_text: str) -> Markup:
    highlighted = []
    for line in yaml_text.splitlines():
        match = re.match(r"^(\s*)([^:\n][^:\n]*?)(:)(.*)$", line)
        if match and not match.group(2).lstrip().startswith("-"):
            indent, key, colon, rest = match.groups()
            highlighted.append(
                f'{escape(indent)}<span class="yaml-key">{escape(key)}</span>'
                f'<span class="yaml-punctuation">{escape(colon)}</span>{escape(rest)}'
            )
        else:
            highlighted.append(str(escape(line)))
    return Markup("\n".join(highlighted))


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
