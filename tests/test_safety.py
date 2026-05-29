from __future__ import annotations

import pytest

from dictate.safety import validate_backend_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:8080/v1",
        "https://openrouter.ai/api/v1",
        "https://api.openai.com/v1",
        "http://10.0.0.5:8000",
        "http://192.168.1.42:11434",
        "http://[::1]:8080",
    ],
)
def test_allows_safe_urls(url: str) -> None:
    validate_backend_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/v2/credentials/",
        "http://[fe80::1]:80/",
        "http://0.0.0.0/v1",
        "http://224.0.0.1/v1",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/v1",
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/_stuff",
        "ftp://example.com/",
        "",
        "://no-scheme",
    ],
)
def test_blocks_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_backend_url(url)


def test_backend_spec_rejects_metadata_service() -> None:
    from dictate.config import BackendSpec

    with pytest.raises(ValueError):
        BackendSpec(
            name="evil",
            base_url="http://169.254.169.254/latest",
            api_key_env=None,
            default_model="x",
            redact=False,
        )
