from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from dictate.config import Config
from dictate.webui.server import create_app


@pytest.fixture
def history_path(tmp_path: Path) -> Path:
    path = tmp_path / "history.jsonl"
    now = datetime.now(UTC)
    rows = [
        {
            "ts": (now - timedelta(days=1)).isoformat(),
            "raw": "foo write a function",
            "cleaned": "Write a function.",
            "preset": "code",
            "frontmost": {"bundle_id": "com.apple.dt.Xcode", "app_name": "Xcode"},
            "metrics": {"backend": "ollama", "latency_ms": 1200, "used_fallback": False},
            "redactions": [{"name": "openai_key", "count": 1}],
        },
        {
            "ts": (now - timedelta(days=40)).isoformat(),
            "raw": "bar meeting note",
            "cleaned": "Bar meeting note.",
            "preset": "chat",
            "frontmost": {"bundle_id": "com.apple.TextEdit", "app_name": "TextEdit"},
            "metrics": {"backend": "openrouter", "latency_ms": 800, "used_fallback": True},
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def cfg(tmp_path: Path, history_path: Path) -> Config:
    return Config(root=tmp_path, settings={"history": {"path": str(history_path)}})


@pytest.fixture
def client(cfg: Config) -> TestClient:
    tc = TestClient(create_app(cfg), client=("127.0.0.1", 50000))
    tc.headers.update({"X-Dictate-WebUI": "1"})
    return tc


@pytest.fixture
def empty_client(tmp_path: Path) -> TestClient:
    cfg = Config(root=tmp_path, settings={"history": {"path": str(tmp_path / "empty.jsonl")}})
    tc = TestClient(create_app(cfg), client=("127.0.0.1", 50000))
    tc.headers.update({"X-Dictate-WebUI": "1"})
    return tc


def test_index_returns_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'class="brand-name"' in response.text
    assert "Dictate" in response.text
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; script-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_empty_state_rendered(empty_client: TestClient) -> None:
    response = empty_client.get("/history")
    assert response.status_code == 200
    assert "No dictations yet" in response.text


def test_dashboard_route_returns_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert ">Dashboard<" in response.text
    assert "kpi-row" in response.text


def test_history_route_returns_table(client: TestClient) -> None:
    response = client.get("/history")
    assert response.status_code == 200
    assert "transcripts" in response.text


def test_dashboard_api_returns_kpis_and_health(client: TestClient) -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"today", "recent", "health", "totals"}
    assert {"count", "chars", "avg_latency_ms", "fallback_rate"} <= set(body["today"])
    assert isinstance(body["recent"], list)
    assert len(body["recent"]) <= 6
    assert "active_backend" in body["health"]
    assert "permissions" in body["health"]
    assert "entries" in body["totals"]


def test_dark_mode_css_present(client: TestClient) -> None:
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert "prefers-color-scheme: dark" in response.text
    assert "--bg:" in response.text
    assert "var(--fg)" in response.text


def test_nav_has_history_link(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/history"' in response.text
    assert ">History<" in response.text


def test_api_transcripts_returns_fixture_entries(client: TestClient) -> None:
    response = client.get("/api/transcripts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    expected_id = hashlib.sha256(
        f"{data[0]['ts']}|{data[0]['cleaned'][:200]}".encode()
    ).hexdigest()[:12]
    assert data[0]["id"] == expected_id
    assert data[1]["raw"] == "foo write a function"


def test_api_transcripts_filters_q_and_preset(client: TestClient) -> None:
    response = client.get("/api/transcripts", params={"q": "foo", "preset": "code"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["preset"] == "code"
    assert "foo" in data[0]["raw"]


def test_delete_transcript_removes_jsonl_entry(client: TestClient, history_path: Path) -> None:
    entry_id = client.get("/api/transcripts").json()[0]["id"]
    response = client.delete(f"/api/transcripts/{quote(entry_id, safe='')}")
    assert response.status_code == 204
    rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["raw"] == "foo write a function"


def test_stats_returns_expected_shape(client: TestClient) -> None:
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["by_preset"]["code"] == 1
    assert data["by_backend"]["ollama"] == 1
    assert "avg_latency_ms" in data
    assert "fallback_rate" in data


def test_export_csv_returns_header(client: TestClient) -> None:
    response = client.get("/api/export", params={"format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    rows = list(csv.reader(StringIO(response.text)))
    assert rows[0] == [
        "id",
        "ts",
        "preset",
        "app",
        "backend",
        "latency_ms",
        "raw",
        "cleaned",
    ]
    assert len(rows) == 3


def test_loopback_middleware_rejects_non_loopback(cfg: Config) -> None:
    blocked_client = TestClient(create_app(cfg), client=("10.1.2.3", 50000))
    response = blocked_client.get("/api/stats")
    assert response.status_code == 403


def test_csrf_blocks_mutations_without_header(cfg: Config) -> None:
    """A malicious cross-origin page hitting localhost POSTs without our custom
    header must be rejected, otherwise CSRF on settings/purge/delete is trivial."""
    bare = TestClient(create_app(cfg), client=("127.0.0.1", 50000))
    assert bare.get("/api/stats").status_code == 200  # GET still works
    assert bare.post("/api/settings/pref", json={"key": "webui.autostart", "value": False}).status_code == 403
    assert bare.post("/api/purge", json={"older_than_days": 1}).status_code == 403
    assert bare.delete("/api/transcripts/anything").status_code == 403


def test_csrf_allows_mutations_with_header(cfg: Config) -> None:
    ok = TestClient(create_app(cfg), client=("127.0.0.1", 50000))
    ok.headers.update({"X-Dictate-WebUI": "1"})
    res = ok.post("/api/settings/pref", json={"key": "webui.autostart", "value": False})
    assert res.status_code == 200


def test_clickjacking_and_csp_headers_present(client: TestClient) -> None:
    res = client.get("/")
    assert res.headers.get("X-Frame-Options") == "DENY"
    csp = res.headers.get("Content-Security-Policy") or ""
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp


def test_history_path_symlink_is_refused(tmp_path: Path) -> None:
    """Hostile config that aims history.path at e.g. ~/.ssh/authorized_keys
    must not be writable through dictate."""
    import os as _os

    from dictate.webui.store import HistoryStore

    target = tmp_path / "real.jsonl"
    target.write_text(json.dumps({"ts": "2025-01-01T00:00:00Z", "raw": "hi"}) + "\n")
    link = tmp_path / "history.jsonl"
    _os.symlink(target, link)
    cfg = Config(root=tmp_path, settings={"history": {"path": str(link)}})
    store = HistoryStore(cfg)
    with pytest.raises(PermissionError):
        store._write_rows_unlocked([{"ts": "2025-01-01T00:00:00Z", "raw": "hi"}])
