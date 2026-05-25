from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from dictate.config import BackendSpec, load_config, was_load_failure


@pytest.fixture
def cfg_root(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "logging": {"level": "DEBUG", "file": "~/custom/log.txt"},
                "cleanup": {"backend": "ollama", "privacy_backend": "ollama"},
                "history": {"path": "$HOME/hist.jsonl"},
            }
        )
    )
    (cfg / "backends.yaml").write_text(
        yaml.safe_dump(
            {
                "ollama": {
                    "base_url": "http://x/v1/",
                    "api_key_env": "FAKE_KEY",
                    "default_model": "m",
                    "redact": True,
                    "health_path": "/ping",
                },
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "default_model": "openai/gpt-4o-mini",
                    "redact": True,
                },
            }
        )
    )
    (cfg / "presets.yaml").write_text(
        yaml.safe_dump({"default": {"system": "you are helpful"}, "selection_suffix": " ctx"})
    )
    (cfg / "commands.yaml").write_text(yaml.safe_dump([]))
    (cfg / "app_map.yaml").write_text(yaml.safe_dump({"com.app.notes": "code"}))
    (cfg / "redact.yaml").write_text(yaml.safe_dump([]))
    return tmp_path


class TestBackendSpec:
    def test_auth_headers_with_key(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret")
        b = BackendSpec("x", "http://x", "MY_KEY", "m", False)
        assert b.auth_headers() == {"Authorization": "Bearer secret"}
        assert b.has_api_key is True

    def test_auth_headers_without_key_env(self):
        b = BackendSpec("ollama", "http://x", None, "m", False)
        assert b.auth_headers() == {}
        assert b.requires_api_key is False
        assert b.has_api_key is True

    def test_auth_headers_when_required_but_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        b = BackendSpec("x", "http://x", "MISSING", "m", False)
        assert b.auth_headers() == {}
        assert b.has_api_key is False
        with pytest.raises(ValueError, match="MISSING"):
            b.ensure_api_key()

    def test_url_joins_base_and_path(self):
        b = BackendSpec("x", "http://x/v1", None, "m", False)
        assert b.url("chat/completions") == "http://x/v1/chat/completions"
        assert b.url("/chat") == "http://x/v1/chat"

    def test_health_url_uses_health_path(self):
        b = BackendSpec("x", "http://x/v1", None, "m", False, health_path="/ping")
        assert b.health_url == "http://x/v1/ping"


class TestConfig:
    def test_load_reads_all_files(self, cfg_root):
        c = load_config(cfg_root)
        assert c.settings["logging"]["level"] == "DEBUG"
        assert "ollama" in c.backends_raw
        assert "default" in c.presets
        assert c.app_map == {"com.app.notes": "code"}

    def test_get_dotted_lookup(self, cfg_root):
        c = load_config(cfg_root)
        assert c.get("logging.level") == "DEBUG"
        assert c.get("missing.key", "fallback") == "fallback"
        assert c.get("logging.nope.deeper", 42) == 42

    def test_backend_strips_trailing_slash_on_base_url(self, cfg_root):
        c = load_config(cfg_root)
        assert c.backend("ollama").base_url == "http://x/v1"

    def test_backend_unknown_raises(self, cfg_root):
        c = load_config(cfg_root)
        with pytest.raises(KeyError, match="ghost"):
            c.backend("ghost")

    def test_active_backend_follows_settings(self, cfg_root):
        c = load_config(cfg_root)
        assert c.active_backend.name == "ollama"

    def test_privacy_backend_name(self, cfg_root):
        c = load_config(cfg_root)
        assert c.privacy_backend_name == "ollama"

    def test_path_expansion(self, cfg_root, monkeypatch):
        monkeypatch.setenv("HOME", "/tmp/fakehome")
        c = load_config(cfg_root)
        assert c.log_path == "/tmp/fakehome/custom/log.txt"
        assert c.history_path == "/tmp/fakehome/hist.jsonl"

    def test_models_dir_default(self, cfg_root):
        c = load_config(cfg_root)
        assert c.models_dir == cfg_root / "models"

    def test_onboarded_marker(self, cfg_root):
        c = load_config(cfg_root)
        assert c.onboarded_marker == cfg_root / ".onboarded"

    def test_project_search_roots_default(self, cfg_root):
        c = load_config(cfg_root)
        roots = c.project_search_roots
        assert all(isinstance(p, Path) for p in roots)
        names = {p.name for p in roots}
        assert {"Developer", "Projects", "code", "src"} <= names

    def test_project_search_roots_configured(self, cfg_root):
        # rewrite settings.yaml with an explicit list
        s = cfg_root / "config" / "settings.yaml"
        data = yaml.safe_load(s.read_text())
        data["context"] = {"project_search_roots": ["~/Work", "/opt/code"]}
        s.write_text(yaml.safe_dump(data))
        c = load_config(cfg_root)
        roots = c.project_search_roots
        assert roots[0] == Path(os.path.expanduser("~/Work"))
        assert roots[1] == Path("/opt/code")

    def test_preset_for_bundle_uses_app_map(self, cfg_root):
        c = load_config(cfg_root)
        assert c.preset_for_bundle("com.app.notes") == "code"
        assert c.preset_for_bundle("com.unknown") == "default"
        assert c.preset_for_bundle(None) == "default"

    def test_preset_falls_back_to_default(self, cfg_root):
        c = load_config(cfg_root)
        assert c.preset("ghost") == c.preset("default")

    def test_fallback_chain_default(self, cfg_root):
        c = load_config(cfg_root)
        assert c.fallback_chain == ["ollama", "raw"]

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "settings.yaml").write_text("cleanup: [unterminated\n")

        c = load_config(tmp_path)
        failed, error = was_load_failure()

        assert c.fallback_chain == ["ollama", "raw"]
        assert c.backend("ollama").base_url == "http://127.0.0.1:11434/v1"
        assert failed is True
        assert error is not None
        assert "settings.yaml" in error
        assert "ParserError" in error or "YAMLError" in error


def test_persist_pref_overlay_survives_reload(tmp_path):
    import yaml

    from dictate.config import Config

    root = tmp_path
    (root / "config").mkdir()
    (root / "config" / "settings.yaml").write_text(
        yaml.safe_dump({"cleanup": {"enabled": True}, "vad": {"threshold": 0.35}})
    )
    cfg = Config.load(root=root)
    assert cfg.get("cleanup.enabled") is True

    cfg.persist_pref("cleanup.enabled", False)
    assert cfg.get("cleanup.enabled") is False
    assert (root / "user_prefs.yaml").exists()

    cfg2 = Config.load(root=root)
    assert cfg2.get("cleanup.enabled") is False
    assert cfg2.get("vad.threshold") == 0.35


def test_set_does_not_persist(tmp_path):
    import yaml

    from dictate.config import Config

    root = tmp_path
    (root / "config").mkdir()
    (root / "config" / "settings.yaml").write_text(yaml.safe_dump({"cleanup": {"enabled": True}}))
    cfg = Config.load(root=root)
    cfg.set("cleanup.enabled", False)
    assert cfg.get("cleanup.enabled") is False
    assert not (root / "user_prefs.yaml").exists()
    cfg2 = Config.load(root=root)
    assert cfg2.get("cleanup.enabled") is True
