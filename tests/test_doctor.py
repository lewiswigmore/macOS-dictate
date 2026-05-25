from __future__ import annotations

from pathlib import Path

import yaml

from dictate import doctor
from dictate.config import Config


class _Perms:
    def __init__(self, accessibility: bool = True, microphone: bool = True) -> None:
        self.accessibility = accessibility
        self.microphone = microphone

    def check_accessibility(self) -> bool:
        return self.accessibility

    def check_microphone(self) -> bool:
        return self.microphone

    def check_input_monitoring(self) -> bool:
        return True


class _Health:
    def __init__(self, config: Config) -> None:
        self.status = {name: {"ok": True, "error": None} for name in config.backends_raw}

    def ping_once(self, name: str) -> bool:
        self.status[name] = {"ok": True, "error": None}
        return True


def _config(root: Path) -> Config:
    config_dir = root / "config"
    (config_dir / "vocab").mkdir(parents=True)
    for name in ("code.txt", "work.txt", "personal.txt"):
        (config_dir / "vocab" / name).write_text("", encoding="utf-8")
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "asr": {"model": "small.en"},
                "history": {"path": str(root / "history.jsonl")},
                "logging": {"file": str(root / "logs" / "dictate.log")},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backends.yaml").write_text(
        yaml.safe_dump(
            {
                "ollama": {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key_env": None,
                    "default_model": "qwen2.5:3b-instruct",
                    "redact": False,
                    "health_path": "/models",
                }
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "presets.yaml").write_text(
        yaml.safe_dump({"default": {}, "code": {}, "work": {}, "personal": {}}),
        encoding="utf-8",
    )
    for name in ("commands.yaml", "app_map.yaml", "redact.yaml"):
        (config_dir / name).write_text(
            yaml.safe_dump({} if name == "app_map.yaml" else []), encoding="utf-8"
        )
    return Config.load(root)


def test_doctor_prints_sections_and_exits_zero_when_checks_ok(monkeypatch, tmp_path, capsys):
    config = _config(tmp_path)
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "Permissions", lambda: _Perms())
    monkeypatch.setattr(doctor, "HealthMonitor", _Health)
    monkeypatch.setattr(doctor, "_ollama_models", lambda _config, _name: "qwen2.5:3b-instruct")
    monkeypatch.setattr(
        doctor,
        "_model_lines",
        lambda _config: [
            doctor.CheckLine(doctor.OK, "Whisper", "small.en (present)"),
            doctor.CheckLine(doctor.OK, "Silero VAD", "present"),
        ],
    )
    monkeypatch.setattr(doctor, "_audio_lines", lambda: (["  Default input:    Test Mic"], []))

    assert doctor.run() == 0
    out = capsys.readouterr().out
    assert "dictate doctor" in out
    assert "System" in out
    assert "Permissions" in out
    assert "Backends" in out
    assert "Configuration" in out


def test_doctor_exits_one_when_permission_denied(monkeypatch, tmp_path, capsys):
    config = _config(tmp_path)
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "Permissions", lambda: _Perms(microphone=False))
    monkeypatch.setattr(doctor, "HealthMonitor", _Health)
    monkeypatch.setattr(doctor, "_ollama_models", lambda _config, _name: None)
    monkeypatch.setattr(doctor, "_model_lines", lambda _config: [])
    monkeypatch.setattr(doctor, "_audio_lines", lambda: (["  Default input:    Test Mic"], []))

    assert doctor.run() == 1
    out = capsys.readouterr().out
    assert "✗ Microphone" in out
    assert "Privacy & Security → Microphone" in out
