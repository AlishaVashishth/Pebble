"""Config: endpoint normalization and secret redaction."""

from __future__ import annotations

from pebble.config import Settings, load_settings, normalize_endpoint


def test_endpoint_v1_suffix_is_stripped():
    assert normalize_endpoint("https://x.openai.azure.com/openai/v1") == (
        "https://x.openai.azure.com"
    )
    assert normalize_endpoint("https://x.openai.azure.com/openai/v1/") == (
        "https://x.openai.azure.com"
    )


def test_plain_endpoint_is_untouched():
    assert normalize_endpoint("https://x.openai.azure.com") == "https://x.openai.azure.com"
    assert normalize_endpoint(None) is None
    assert normalize_endpoint("  ") is None


def test_real_env_endpoint_is_normalized():
    settings = load_settings()
    if settings.azure_endpoint:
        assert not settings.azure_endpoint.endswith("/openai/v1")


def test_repr_never_shows_secrets():
    settings = Settings(
        azure_endpoint="https://x.openai.azure.com",
        azure_api_key="super-secret-key",
        azure_deployment="gpt-5-mini",
        azure_speech_key="speech-secret",
    )
    text = repr(settings)
    assert "super-secret-key" not in text
    assert "speech-secret" not in text
    assert "REDACTED" in text
    assert "gpt-5-mini" in text  # non-secret config is still visible
