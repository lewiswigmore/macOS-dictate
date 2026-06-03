"""Tests for the silero-vad model download integrity check (H2 in #51).

These tests exercise the SHA256-verifying download path without touching
the network: they monkeypatch ``httpx.Client`` so the streamed bytes come
from a fixture string. The model file is never loaded into onnxruntime
here — that surface is covered in ``test_vad.py`` against the real model
when present.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dictate import vad as vad_module


@pytest.fixture
def good_bytes() -> bytes:
    return b"verified silero bytes\n" * 1024


@pytest.fixture
def bad_bytes() -> bytes:
    return b"tampered ONNX payload" * 1024


@pytest.fixture
def good_sha(good_bytes: bytes) -> str:
    return hashlib.sha256(good_bytes).hexdigest()


@pytest.fixture
def _pin_sha(monkeypatch: pytest.MonkeyPatch, good_sha: str) -> None:
    """Pin the module-level expected SHA256 to the fixture hash so we can
    test the verifier end-to-end without depending on the real upstream
    bytes (which would tie tests to a network fetch)."""
    monkeypatch.setattr(vad_module, "MODEL_SHA256", good_sha)


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_bytes(self, chunk_size: int) -> Any:
        view = memoryview(self._payload)
        for i in range(0, len(view), chunk_size):
            yield bytes(view[i : i + chunk_size])

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeClient:
    def __init__(self, payload: bytes, status: int = 200, **_: Any) -> None:
        self._payload = payload
        self._status = status
        self.requested_urls: list[str] = []

    def stream(self, _method: str, url: str) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self._payload, status=self._status)

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> dict[str, _FakeClient]:
    client_holder: dict[str, _FakeClient] = {}

    def fake_client_factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(payload, **kwargs)
        client_holder["client"] = client
        return client

    fake_httpx = SimpleNamespace(Client=fake_client_factory)
    monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)
    return client_holder


def test_validates_https_only() -> None:
    with pytest.raises(RuntimeError, match="non-https"):
        vad_module._validate_model_url("http://raw.githubusercontent.com/x")


def test_validates_pinned_host() -> None:
    with pytest.raises(RuntimeError, match="unexpected host"):
        vad_module._validate_model_url("https://evil.example.com/silero_vad.onnx")


def test_module_url_uses_pinned_host_and_tag() -> None:
    """MODEL_URL must point at the pinned host on a tagged ref, never at
    ``master`` (mutable upstream that defeats the SHA pin's intent)."""
    assert vad_module.MODEL_URL.startswith("https://raw.githubusercontent.com/")
    assert "/master/" not in vad_module.MODEL_URL
    assert vad_module._MODEL_TAG in vad_module.MODEL_URL


def test_download_verifies_sha256_and_keeps_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    good_bytes: bytes,
    _pin_sha: None,
) -> None:
    holder = _patch_httpx(monkeypatch, good_bytes)
    dest = tmp_path / "silero_vad.onnx"
    assert not dest.exists()

    returned = vad_module._download_model(dest)

    assert returned == dest
    assert dest.read_bytes() == good_bytes
    # Only the pinned URL is contacted; no redirect dance, no fall-back hosts.
    assert holder["client"].requested_urls == [vad_module.MODEL_URL]  # type: ignore[index]


def test_download_rejects_tampered_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_bytes: bytes,
    _pin_sha: None,
) -> None:
    _patch_httpx(monkeypatch, bad_bytes)
    dest = tmp_path / "silero_vad.onnx"

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        vad_module._download_model(dest)
    # Partial / wrong payload must not be left on disk for the next caller
    # to pick up via the cache path.
    assert not dest.exists()


def test_cached_file_with_bad_hash_is_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    good_bytes: bytes,
    bad_bytes: bytes,
    _pin_sha: None,
) -> None:
    """A pre-existing file with the wrong hash — e.g. an attacker writing
    to ``~/dictate/models/silero_vad.onnx`` directly, or a corrupted
    partial download from an older run — must be detected and replaced,
    never blindly trusted. This closes the early-return-on-exists hole in
    the original ``_download_model``."""
    dest = tmp_path / "silero_vad.onnx"
    dest.write_bytes(bad_bytes)
    _patch_httpx(monkeypatch, good_bytes)

    returned = vad_module._download_model(dest)

    assert returned == dest
    assert dest.read_bytes() == good_bytes


def test_cached_file_with_good_hash_is_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    good_bytes: bytes,
    _pin_sha: None,
) -> None:
    """A correctly-hashed cache file must be reused without re-downloading
    — H2's verify-every-load invariant should be a fast hash, not a fresh
    fetch."""
    dest = tmp_path / "silero_vad.onnx"
    dest.write_bytes(good_bytes)

    # If httpx is invoked, this would AttributeError because we haven't
    # patched it. The assertion is that the cache path returns first.
    monkeypatch.delitem(__import__("sys").modules, "httpx", raising=False)

    returned = vad_module._download_model(dest)
    assert returned == dest
    assert dest.read_bytes() == good_bytes


def test_download_failure_cleans_up_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _pin_sha: None,
) -> None:
    class _BoomClient(_FakeClient):
        def stream(self, _method: str, _url: str) -> _FakeResponse:
            raise OSError("network boom")

    def factory(**kwargs: Any) -> _FakeClient:
        return _BoomClient(b"", **kwargs)

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=factory)
    )

    dest = tmp_path / "silero_vad.onnx"
    with pytest.raises(RuntimeError, match="Failed to download"):
        vad_module._download_model(dest)
    assert not dest.exists()
    assert list(dest.parent.glob(".silero_vad.onnx.*.part")) == []


def test_download_rejects_3xx_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _pin_sha: None,
) -> None:
    """With follow_redirects=False, a 3xx response must fail-fast rather
    than silently writing the redirect body to disk."""

    def factory(**kwargs: Any) -> _FakeClient:
        return _FakeClient(b"redirect-body", status=302, **kwargs)

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=factory)
    )

    dest = tmp_path / "silero_vad.onnx"
    with pytest.raises(RuntimeError, match="Failed to download"):
        vad_module._download_model(dest)
    assert not dest.exists()
    assert list(dest.parent.glob(".silero_vad.onnx.*.part")) == []


def test_download_writes_via_tempfile_then_renames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _pin_sha: None,
) -> None:
    """Confirm the success path leaves no .part sibling files behind and the
    bytes at dest are exactly what was streamed (not a partial)."""
    good_bytes = b"silero-onnx-bytes-for-tests"
    monkeypatch.setattr(vad_module, "MODEL_SHA256", hashlib.sha256(good_bytes).hexdigest())
    holder = _patch_httpx(monkeypatch, good_bytes)

    dest = tmp_path / "silero_vad.onnx"
    returned = vad_module._download_model(dest)
    assert returned == dest
    assert dest.read_bytes() == good_bytes
    assert list(dest.parent.glob(".silero_vad.onnx.*.part")) == []
    assert holder["client"].requested_urls == [vad_module.MODEL_URL]
