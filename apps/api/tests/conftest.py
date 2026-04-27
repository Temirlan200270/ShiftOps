"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("JWT_SECRET", "test-secret-must-be-long-enough-32ch")
    monkeypatch.setenv("TG_BOT_TOKEN", "1234567890:TEST_TOKEN_FOR_HMAC_VALIDATION_xx")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "test-secret-token")

    from shiftops_api.config import get_settings

    get_settings.cache_clear()
