"""Pipeline-level checks for `_phase_redact`.

The redact phase is responsible for stripping secret material from any text
that may leave the Mac via a cloud cleanup backend. It must cover both the
raw transcript and the AX-sourced selection (sibling to the few-shot fix in
#52). These tests pin the call-site wiring; unit-level redaction behaviour
is already covered in ``test_redact.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dictate.app import App, _PipelineCtx
from dictate.config import BackendSpec, Config
from dictate.redact import Redactor

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def redactor() -> Redactor:
    return Redactor(Config.load(REPO_ROOT).redact_patterns)


def _stub_app(redactor: Redactor, *, redact: bool) -> SimpleNamespace:
    backend = BackendSpec(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env=None,
        default_model="x",
        redact=redact,
    )
    return SimpleNamespace(
        config=SimpleNamespace(active_backend=backend),
        redactor=redactor,
    )


def test_redacts_raw_when_backend_redacts(redactor: Redactor) -> None:
    app = _stub_app(redactor, redact=True)
    ctx = _PipelineCtx(raw="my key is sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc")
    App._phase_redact(app, ctx)
    assert "sk-" not in ctx.raw
    assert any(r.get("name") == "openai_key" for r in ctx.redactions)
    assert "openai_key" in ctx.metrics["redactions"]


def test_redacts_selection_when_backend_redacts(redactor: Redactor) -> None:
    app = _stub_app(redactor, redact=True)
    ctx = _PipelineCtx(
        raw="rewrite the highlighted thing for me",
        selection="export OPENAI_API_KEY=sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc",
    )
    App._phase_redact(app, ctx)
    # The literal secret must not survive to be interpolated into the
    # cleanup system prompt at ``CleanupClient._build_messages``.
    assert "sk-abc123" not in (ctx.selection or "")
    assert "«REDACTED:openai_key»" in (ctx.selection or "")
    # Selection hits show up alongside raw hits in the audit metric.
    assert "openai_key" in ctx.metrics["redactions"]


def test_redaction_metrics_include_raw_and_selection_hits(redactor: Redactor) -> None:
    app = _stub_app(redactor, redact=True)
    ctx = _PipelineCtx(
        raw="aws is AKIAIOSFODNN7EXAMPLE",
        selection="github token ghp_" + "a" * 30,
    )
    App._phase_redact(app, ctx)
    names = ctx.metrics["redactions"]
    assert "aws_access_key" in names
    assert "github_pat" in names


def test_skips_redaction_when_backend_does_not_redact(redactor: Redactor) -> None:
    app = _stub_app(redactor, redact=False)
    ctx = _PipelineCtx(
        raw="my key is sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc",
        selection="bearer eyJabcdef.ghijklmnop.qrstuvwxyz",
    )
    App._phase_redact(app, ctx)
    # Local backends keep the prompt as-is; redaction policy lives in
    # backends.yaml. The metric should still be present but empty.
    assert "sk-" in ctx.raw
    assert "bearer" in (ctx.selection or "").lower()
    assert ctx.metrics["redactions"] == []


def test_empty_selection_is_a_noop(redactor: Redactor) -> None:
    app = _stub_app(redactor, redact=True)
    ctx = _PipelineCtx(raw="hello", selection=None)
    App._phase_redact(app, ctx)
    assert ctx.selection is None


def test_missing_active_backend_does_not_crash(redactor: Redactor) -> None:
    """If backends.yaml is missing the configured backend, redact is a no-op
    rather than a crash — the existing pipeline relies on this fallback to
    keep dictation working while the user fixes their config."""
    class _MissingBackendConfig:
        @property
        def active_backend(self):  # pragma: no cover - behaviour, not value
            raise KeyError("backend missing")

    app = SimpleNamespace(config=_MissingBackendConfig(), redactor=redactor)
    ctx = _PipelineCtx(raw="my key is sk-abc123XXXXXXXXXXXXXXXXXXXXXXabc")
    App._phase_redact(app, ctx)
    assert "sk-" in ctx.raw
    assert ctx.metrics["redactions"] == []
