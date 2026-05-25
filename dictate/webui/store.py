from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dictate._filelock import exclusive_file_lock
from dictate.config import Config
from dictate.logging_setup import get_logger

log = get_logger(__name__)
_HISTORY_FILE_MODE = 0o600


class Frontmost(BaseModel):
    model_config = ConfigDict(extra="allow")

    bundle_id: str | None = None
    app_name: str | None = None
    window_title: str | None = None


class Metrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    backend: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    used_fallback: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def fill_latency_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("latency_ms") is None:
            for alt in ("duration_ms", "asr_ms", "total_ms"):
                if data.get(alt) is not None:
                    data["latency_ms"] = data[alt]
                    break
        return data


class Redaction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    count: int | None = None


class Entry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    index: int
    ts: str | None = None
    raw: str | None = None
    cleaned: str | None = None
    preset: str | None = None
    frontmost: Frontmost | None = None
    selection: str | None = None
    metrics: Metrics | None = None
    redactions: list[Redaction] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def derive_frontmost_and_metrics(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Flat app_bundle / app_name → nested frontmost
        if not data.get("frontmost"):
            bundle = data.get("app_bundle")
            app_name = data.get("app_name")
            if bundle or app_name:
                data["frontmost"] = {
                    "bundle_id": bundle,
                    "app_name": app_name or _app_name_from_bundle(bundle),
                }
        elif isinstance(data.get("frontmost"), dict):
            fm = data["frontmost"]
            if not fm.get("app_name") and fm.get("bundle_id"):
                fm["app_name"] = _app_name_from_bundle(fm["bundle_id"])
        # Promote top-level duration_ms into metrics.latency_ms if metrics missing it
        metrics = data.get("metrics")
        top_duration = data.get("duration_ms")
        if top_duration is not None:
            if not isinstance(metrics, dict):
                metrics = {}
                data["metrics"] = metrics
            if metrics.get("latency_ms") is None and metrics.get("duration_ms") is None:
                metrics["latency_ms"] = top_duration
        return data

    @field_validator("frontmost", "metrics", mode="before")
    @classmethod
    def coerce_optional_object(cls, value: Any) -> Any:
        return value if isinstance(value, dict) or value is None else None

    @field_validator("redactions", mode="before")
    @classmethod
    def coerce_redactions(cls, value: Any) -> Any:
        return value if isinstance(value, list) else []


def _app_name_from_bundle(bundle: str | None) -> str | None:
    if not bundle:
        return None
    tail = bundle.rsplit(".", 1)[-1]
    pretty = {
        "Terminal": "Terminal",
        "Safari": "Safari",
        "Code": "VS Code",
        "iTerm2": "iTerm",
        "Slack": "Slack",
        "TextEdit": "TextEdit",
        "Notes": "Notes",
        "Mail": "Mail",
    }
    return pretty.get(tail, tail)


class HistoryStore:
    def __init__(self, config: Config) -> None:
        self.path = Path(config.history_path)

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
        preset: str | None = None,
        app: str | None = None,
        since: datetime | None = None,
    ) -> list[Entry]:
        entries = self._entries()
        filtered = [entry for entry in entries if self._matches(entry, q, preset, app, since)]
        filtered.reverse()
        return filtered[max(offset, 0) : max(offset, 0) + max(min(limit, 500), 0)]

    def count(self) -> int:
        return len(self._entries())

    def last_updated(self) -> datetime | None:
        timestamps = [dt for entry in self._entries() if (dt := _parse_datetime(entry.ts))]
        return max(timestamps) if timestamps else None

    def get(self, id: str) -> Entry | None:
        for entry in self._entries():
            if entry.id == id or entry.ts == id:
                return entry
        return None

    def neighbors(self, id: str) -> tuple[str | None, str | None]:
        """Return ``(prev_id, next_id)`` in newest-first order for paging."""
        entries = self._entries()
        entries.reverse()
        for i, entry in enumerate(entries):
            if entry.id == id or entry.ts == id:
                prev_id = entries[i - 1].id if i > 0 else None
                next_id = entries[i + 1].id if i + 1 < len(entries) else None
                return prev_id, next_id
        return None, None

    def delete(self, ids: list[str]) -> int:
        wanted = set(ids)
        with exclusive_file_lock(self.path, create_parent=True):
            rows = self._read_rows_unlocked()
            kept: list[dict[str, Any]] = []
            deleted = 0
            for idx, row in rows:
                entry_id = self._id_for(row, idx)
                if entry_id in wanted or row.get("ts") in wanted:
                    deleted += 1
                else:
                    kept.append(row)
            if deleted:
                self._write_rows_unlocked(kept)
            return deleted

    def recent(self, limit: int = 6) -> list[Entry]:
        return self.list(limit=limit)

    def today_summary(self) -> dict[str, Any]:
        """Aggregate today's utterances for the dashboard KPI strip."""
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        today = [
            entry
            for entry in self._entries()
            if (dt := _parse_datetime(entry.ts)) and dt >= start
        ]
        chars = sum(len(entry.cleaned or entry.raw or "") for entry in today)
        latencies = [
            float(entry.metrics.latency_ms)
            for entry in today
            if entry.metrics and isinstance(entry.metrics.latency_ms, int | float)
        ]
        fallback = sum(
            1 for entry in today if entry.metrics and entry.metrics.used_fallback
        )
        return {
            "count": len(today),
            "chars": chars,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2)
            if latencies
            else None,
            "fallback_rate": round(fallback / len(today), 4) if today else 0,
        }

    def stats(self) -> dict[str, Any]:
        entries = self._entries()
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=29)
        by_day = {(cutoff + timedelta(days=i)).date().isoformat(): 0 for i in range(30)}
        by_hour = {h: 0 for h in range(24)}
        by_preset: dict[str, int] = {}
        by_app: dict[str, int] = {}
        by_backend: dict[str, int] = {}
        latencies: list[float] = []
        fallback_count = 0
        total_chars = 0
        local_count = 0
        cloud_backends = {"openrouter", "openai"}

        for entry in entries:
            dt = _parse_datetime(entry.ts)
            if dt and dt >= cutoff:
                by_day[dt.date().isoformat()] = by_day.get(dt.date().isoformat(), 0) + 1
            if dt:
                local_dt = dt.astimezone()
                by_hour[local_dt.hour] = by_hour.get(local_dt.hour, 0) + 1
            by_preset[entry.preset or "unknown"] = by_preset.get(entry.preset or "unknown", 0) + 1
            app_name = (
                entry.frontmost.app_name
                if entry.frontmost and entry.frontmost.app_name
                else "unknown"
            )
            by_app[app_name] = by_app.get(app_name, 0) + 1
            backend_label = "unknown"
            if entry.metrics:
                explicit_backend = entry.metrics.backend or getattr(entry.metrics, "cleanup_backend", None)
                if explicit_backend:
                    backend_label = str(explicit_backend)
                elif getattr(entry.metrics, "cleanup_skipped", None):
                    backend_label = "skipped"
            by_backend[backend_label] = by_backend.get(backend_label, 0) + 1
            if backend_label.lower() not in cloud_backends:
                local_count += 1
            if entry.metrics and isinstance(entry.metrics.latency_ms, int | float):
                latencies.append(float(entry.metrics.latency_ms))
            if entry.metrics and entry.metrics.used_fallback:
                fallback_count += 1
            total_chars += len(entry.cleaned or entry.raw or "")

        total = len(entries)
        p50 = _percentile(latencies, 50)
        p95 = _percentile(latencies, 95)
        return {
            "total": total,
            "total_chars": total_chars,
            "avg_chars": round(total_chars / total, 1) if total else 0,
            "by_day": by_day,
            "by_hour": by_hour,
            "by_preset": by_preset,
            "by_app": dict(sorted(by_app.items(), key=lambda item: item[1], reverse=True)[:10]),
            "by_backend": by_backend,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "fallback_rate": round(fallback_count / total, 4) if total else 0,
            "local_ratio": round(local_count / total, 4) if total else 1.0,
        }

    def export(self, format: Literal["jsonl", "csv", "markdown"]) -> bytes | str:
        if format == "jsonl":
            if not self.path.exists():
                return b""
            with exclusive_file_lock(self.path):
                return self.path.read_bytes()
        entries = self._entries()
        if format == "csv":
            out = StringIO()
            writer = csv.DictWriter(
                out,
                fieldnames=[
                    "id",
                    "ts",
                    "preset",
                    "app",
                    "backend",
                    "latency_ms",
                    "raw",
                    "cleaned",
                ],
            )
            writer.writeheader()
            for entry in entries:
                writer.writerow(
                    {
                        "id": entry.id,
                        "ts": entry.ts or "",
                        "preset": entry.preset or "",
                        "app": entry.frontmost.app_name if entry.frontmost else "",
                        "backend": entry.metrics.backend if entry.metrics else "",
                        "latency_ms": entry.metrics.latency_ms if entry.metrics else "",
                        "raw": entry.raw or "",
                        "cleaned": entry.cleaned or "",
                    }
                )
            return out.getvalue()
        blocks = []
        for entry in entries:
            blocks.append(
                "\n".join(
                    [
                        f"## {entry.ts or entry.id}",
                        f"- Preset: {entry.preset or 'unknown'}",
                        f"- App: {entry.frontmost.app_name if entry.frontmost else 'unknown'}",
                        f"- Backend: {entry.metrics.backend if entry.metrics else 'unknown'}",
                        "",
                        "### Raw",
                        entry.raw or "",
                        "",
                        "### Cleaned",
                        entry.cleaned or "",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(days, 0))
        ids = [
            entry.id
            for entry in self._entries()
            if (dt := _parse_datetime(entry.ts)) and dt < cutoff
        ]
        return self.delete(ids)

    def _entries(self) -> list[Entry]:
        result: list[Entry] = []
        for idx, row in self._rows():
            kind = row.get("type")
            # Only user-facing utterances belong in the transcript history view.
            # `correction` events are written by the learn watcher; `command`
            # events are voice-command audit records.
            if kind not in (None, "utterance"):
                continue
            try:
                result.append(
                    Entry.model_validate({**row, "id": self._id_for(row, idx), "index": idx})
                )
            except Exception as exc:
                log.warning("could not parse history entry %s: %s", idx, exc)
        return result

    def _rows(self) -> list[tuple[int, dict[str, Any]]]:
        if not self.path.exists():
            return []
        with exclusive_file_lock(self.path):
            return self._read_rows_unlocked()

    def _read_rows_unlocked(self) -> list[tuple[int, dict[str, Any]]]:
        if not self.path.exists():
            return []
        rows: list[tuple[int, dict[str, Any]]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("malformed history line %s: %s", idx, line[:80])
                    continue
                if isinstance(row, dict):
                    rows.append((idx, row))
        return rows

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        with exclusive_file_lock(self.path, create_parent=True):
            self._write_rows_unlocked(rows)

    def _write_rows_unlocked(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise PermissionError(
                f"history path {self.path} is a symlink; refusing to write"
            )
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, _HISTORY_FILE_MODE, follow_symlinks=False)
        except (OSError, NotImplementedError):
            os.chmod(tmp, _HISTORY_FILE_MODE)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, _HISTORY_FILE_MODE, follow_symlinks=False)
        except (OSError, NotImplementedError):
            os.chmod(self.path, _HISTORY_FILE_MODE)

    @staticmethod
    def _id_for(row: dict[str, Any], _idx: int) -> str:
        ts = str(row.get("ts") or "missing-ts")
        text = str(row.get("cleaned") or row.get("raw") or row.get("text") or "")
        return hashlib.sha256(f"{ts}|{text[:200]}".encode()).hexdigest()[:12]

    @staticmethod
    def _matches(
        entry: Entry,
        q: str | None,
        preset: str | None,
        app: str | None,
        since: datetime | None,
    ) -> bool:
        if q:
            needle = q.casefold()
            haystack = " ".join(
                [entry.raw or "", entry.cleaned or "", entry.selection or ""]
            ).casefold()
            if needle not in haystack:
                return False
        if preset and preset != entry.preset:
            return False
        if app:
            app_name = entry.frontmost.app_name if entry.frontmost else ""
            bundle_id = entry.frontmost.bundle_id if entry.frontmost else ""
            if app.casefold() not in f"{app_name} {bundle_id}".casefold():
                return False
        if since:
            dt = _parse_datetime(entry.ts)
            if not dt or dt < since:
                return False
        return True


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac, 2)
