from __future__ import annotations

from pathlib import Path

import pytest

from dictate.config import Config
from dictate.redact import Redactor, should_redact_for_backend

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def redactor() -> Redactor:
    config = Config.load(REPO_ROOT)
    return Redactor(config.redact_patterns)


def test_redacts_openai_key(redactor: Redactor) -> None:
    text = "my key is sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc"
    out, hits = redactor.redact(text)
    assert "sk-" not in out
    assert any(h["name"] == "openai_key" for h in hits)
    assert "«REDACTED:openai_key»" in out


def test_redacts_github_pat(redactor: Redactor) -> None:
    token = "ghp_" + "a" * 30
    out, hits = redactor.redact(f"token: {token}")
    assert token not in out
    assert any(h["name"] == "github_pat" for h in hits)


def test_redacts_password_phrase(redactor: Redactor) -> None:
    out, hits = redactor.redact("password is hunter2")
    assert "hunter2" not in out
    assert any(h["name"] == "password_phrase" for h in hits)


def test_redacts_env_assignment(redactor: Redactor) -> None:
    out, hits = redactor.redact("API_KEY=supersecretvalue")
    assert "supersecretvalue" not in out
    assert any(h["name"] == "env_assignment" for h in hits)


def test_no_match_plain_secret_word(redactor: Redactor) -> None:
    text = "This is a secret project I've been working on."
    out, hits = redactor.redact(text)
    assert out == text
    assert hits == []


def test_hit_count(redactor: Redactor) -> None:
    key = "sk-" + "x" * 25
    text = f"{key} and again {key}"
    _, hits = redactor.redact(text)
    hit = next(h for h in hits if h["name"] == "openai_key")
    assert hit["count"] == 2
    # Sample must NOT be stored — it would leak partial secret material into
    # history.jsonl / logs.
    assert "sample" not in hit


def test_should_redact_for_backend() -> None:
    config = Config.load(REPO_ROOT)
    for backend_name in config.backends_raw:
        spec = config.backend(backend_name)
        assert should_redact_for_backend(spec) == spec.redact


def test_redact_pairs_redacts_both_halves(redactor: Redactor) -> None:
    pairs = [
        ("my key is sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc", "use sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc"),
        ("nothing sensitive here", "still clean"),
    ]
    out = redactor.redact_pairs(pairs)
    assert len(out) == 2
    assert "sk-" not in out[0][0]
    assert "sk-" not in out[0][1]
    assert "«REDACTED:openai_key»" in out[0][0]
    assert "«REDACTED:openai_key»" in out[0][1]
    assert out[1] == ("nothing sensitive here", "still clean")


def test_redact_pairs_empty() -> None:
    redactor = Redactor([])
    assert redactor.redact_pairs([]) == []
