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


class TestPurgeApiValidation:
    """``older_than_days=0`` against /api/purge would wipe every transcript
    with a parseable timestamp. The HTML form is bounded by ``min="1"`` and
    the CLI/auto-purge path early-returns on ``days <= 0``; the API must
    enforce the same contract so a typo or intercepted request cannot
    destroy the whole history."""

    def test_zero_days_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/purge", json={"older_than_days": 0})
        assert resp.status_code == 422

    def test_negative_days_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/purge", json={"older_than_days": -1})
        assert resp.status_code == 422

    def test_two_day_cutoff_only_deletes_older_entries(
        self, cfg: Config, history_path: Path
    ) -> None:
        from dictate.webui.store import HistoryStore

        store = HistoryStore(cfg)
        before = store.count()
        # Fixture has a 1-day-old entry and a 40-day-old entry; with a
        # 2-day cutoff only the 40-day one should fall off.
        deleted = store.purge_older_than(2)
        assert deleted == 1
        assert store.count() == before - 1

    def test_store_purge_zero_is_noop_defence_in_depth(
        self, cfg: Config, history_path: Path
    ) -> None:
        """Even with the API tightened, the store itself must refuse
        ``days <= 0`` so future call sites (scripts, tests) inherit the
        same safety."""
        from dictate.webui.store import HistoryStore

        store = HistoryStore(cfg)
        before = store.count()
        assert store.purge_older_than(0) == 0
        assert store.purge_older_than(-5) == 0
        assert store.count() == before


def test_webui_store_tmp_file_is_0o600(tmp_path: Path, monkeypatch) -> None:
    """The webui ``HistoryStore._write_rows_unlocked`` path used to open
    its tmp file with ``Path.open("w")`` which honours the process umask
    (typically 0o022 on macOS) and briefly produced a 0o644 sibling
    containing the full history. Switching to ``tempfile.NamedTemporaryFile``
    makes the tmp file 0o600 from creation. Verify by spying on the
    tempfile call and recording the mode immediately after creation."""
    import os as _os
    import stat as _stat
    import tempfile as _tempfile

    from dictate.webui.store import HistoryStore

    history_path = tmp_path / "history.jsonl"
    cfg = Config(root=tmp_path, settings={"history": {"path": str(history_path)}})
    store = HistoryStore(cfg)

    observed_modes: list[int] = []
    real_ntf = _tempfile.NamedTemporaryFile

    def spy(*args, **kwargs):
        handle = real_ntf(*args, **kwargs)
        observed_modes.append(_stat.S_IMODE(_os.stat(handle.name).st_mode))
        return handle

    monkeypatch.setattr("dictate.webui.store.tempfile.NamedTemporaryFile", spy)
    store._write_rows_unlocked(
        [{"ts": "2025-01-01T00:00:00Z", "raw": "secret-bearing line"}]
    )

    assert observed_modes, "expected NamedTemporaryFile to be called"
    assert all(m == 0o600 for m in observed_modes), (
        f"expected 0o600 from the moment of tmp creation, got "
        f"{[oct(m) for m in observed_modes]}"
    )
    assert (history_path.stat().st_mode & 0o777) == 0o600
    leftovers = [
        p.name
        for p in tmp_path.iterdir()
        if p.name != history_path.name and p.name.endswith(".tmp")
    ]
    assert leftovers == [], f"expected no tmp leftovers, got {leftovers}"
