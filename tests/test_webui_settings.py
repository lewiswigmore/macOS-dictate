from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dictate.config import Config
from dictate.webui import routes
from dictate.webui.server import create_app


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        root=tmp_path,
        settings={
            "history": {"path": str(tmp_path / "history.jsonl")},
            "cleanup": {"backend": "ollama", "api_token": "super-secret-token"},
        },
    )


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg), client=("127.0.0.1", 50000))


def test_settings_returns_html_and_resolved_path(client: TestClient, cfg: Config) -> None:
    response = client.get("/settings")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Common toggles below" in response.text
    assert str((cfg.root / "config" / "settings.yaml").resolve(strict=False)) in response.text
    assert "super-secret-token" not in response.text
    assert "***" in response.text


def test_settings_shows_load_failure_banner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes.config_module, "was_load_failure", lambda: (True, "bad yaml")
    )

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Config failed to load — using defaults. Error: bad yaml" in response.text


def test_settings_refuses_non_loopback_requests(cfg: Config) -> None:
    blocked_client = TestClient(create_app(cfg), client=("10.1.2.3", 50000))

    response = blocked_client.get("/settings")

    assert response.status_code == 403


def test_settings_is_read_only(client: TestClient) -> None:
    assert client.post("/settings").status_code == 405
    assert client.put("/settings").status_code == 405
    assert client.delete("/settings").status_code == 405


def test_pref_update_persists(client: TestClient, cfg: Config) -> None:
    response = client.post(
        "/api/settings/pref",
        json={"key": "webui.autostart", "value": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["value"] is False
    assert cfg.get("webui.autostart") is False
    assert cfg.prefs_path.exists()


def test_pref_update_rejects_unknown_key(client: TestClient) -> None:
    response = client.post(
        "/api/settings/pref",
        json={"key": "hotkey.modifier", "value": "shift"},
    )
    assert response.status_code == 400
    assert "not editable" in response.text


def test_pref_update_rejects_bad_enum(client: TestClient) -> None:
    response = client.post(
        "/api/settings/pref",
        json={"key": "logging.level", "value": "TRACE"},
    )
    assert response.status_code == 400
