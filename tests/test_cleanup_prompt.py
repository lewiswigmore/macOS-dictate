from __future__ import annotations

from pathlib import Path

import pytest

from dictate.cleanup import CleanupClient
from dictate.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = Config(root=tmp_path)
    cfg.presets = {
        "default": {
            "system": (
                "You are a voice-typing assistant. Clean up the text. "
                "Preserve these terms verbatim if they appear: {vocab}"
            )
        },
        "code": {
            "system": (
                "Code editor mode. No capitalisation. Preserve these terms verbatim: {vocab}"
            )
        },
        "selection_suffix": (
            "\n\nThe user has the following text selected. "
            "Rewrite it per the instruction.\n\nSELECTION:\n---\n{selection}\n---"
        ),
    }
    cfg.settings = {
        "cleanup": {
            "backend": "ollama",
            "fallback_chain": ["ollama", "raw"],
        }
    }
    cfg.backends_raw = {
        "ollama": {
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key_env": None,
            "default_model": "qwen2.5:3b-instruct",
            "redact": False,
        }
    }
    return cfg


def test_first_message_is_system(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("hello", "default", [])
    assert msgs[0]["role"] == "system"


def test_system_contains_preset_prompt(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("hello world", "default", ["pytest", "ruff"])
    assert "voice-typing assistant" in msgs[0]["content"]
    assert "Clean up the text" in msgs[0]["content"]


def test_vocab_interpolated_in_system(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("test", "default", ["pytest", "httpx", "ruff"])
    assert "pytest, httpx, ruff" in msgs[0]["content"]
    assert "{vocab}" not in msgs[0]["content"]


def test_empty_vocab_placeholder_replaced(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("test", "default", [])
    assert "{vocab}" not in msgs[0]["content"]


def test_no_selection_suffix_when_none(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("test", "default", ["word"])
    assert "SELECTION" not in msgs[0]["content"]
    assert "{selection}" not in msgs[0]["content"]


def test_selection_suffix_added_when_provided(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("rewrite it", "default", ["word"], selection="old text here")
    system = msgs[0]["content"]
    assert "old text here" in system
    assert "SELECTION" in system


def test_selection_suffix_not_added_when_none(config: Config) -> None:
    client_a = CleanupClient(config)
    client_b = CleanupClient(config)
    without = client_a._build_messages("x", "default", [])
    with_sel = client_b._build_messages("x", "default", [], selection="some selected")
    assert len(with_sel[0]["content"]) > len(without[0]["content"])


def test_few_shot_pairs_in_correct_order(config: Config) -> None:
    client = CleanupClient(config)
    few_shot = [("raw one", "clean one"), ("raw two", "clean two")]
    msgs = client._build_messages("final input", "default", [], few_shot=few_shot)
    # indices: 0=system, 1=user, 2=assistant, 3=user, 4=assistant, 5=user(final)
    assert msgs[1] == {"role": "user", "content": "raw one"}
    assert msgs[2] == {"role": "assistant", "content": "clean one"}
    assert msgs[3] == {"role": "user", "content": "raw two"}
    assert msgs[4] == {"role": "assistant", "content": "clean two"}


def test_final_user_message_is_raw_transcript(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("my raw transcript", "default", [])
    assert msgs[-1] == {"role": "user", "content": "my raw transcript"}


def test_final_user_message_is_raw_with_few_shot(config: Config) -> None:
    client = CleanupClient(config)
    few_shot = [("ex in", "ex out")]
    msgs = client._build_messages("dictated text", "default", [], few_shot=few_shot)
    assert msgs[-1] == {"role": "user", "content": "dictated text"}


def test_total_message_count_no_few_shot(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("test", "default", [])
    assert len(msgs) == 2  # system + user


def test_total_message_count_with_few_shot(config: Config) -> None:
    client = CleanupClient(config)
    few_shot = [("a", "b"), ("c", "d")]
    msgs = client._build_messages("test", "default", [], few_shot=few_shot)
    assert len(msgs) == 6  # system + 2*(user+assistant) + user


def test_code_preset_selected(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("snake case my var", "code", ["main_loop"])
    system = msgs[0]["content"]
    assert "Code editor mode" in system
    assert "main_loop" in system


def test_unknown_preset_falls_back_to_default(config: Config) -> None:
    client = CleanupClient(config)
    msgs = client._build_messages("test", "nonexistent_preset", [])
    # config.preset() falls back to "default" when name not found
    assert "voice-typing assistant" in msgs[0]["content"]
