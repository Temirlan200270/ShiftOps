"""Production secret validation at API startup."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from shiftops_api.config.settings import Settings
from shiftops_api.config.production_guard import assert_production_secrets_configured


def test_noop_when_not_production() -> None:
    s = Settings(app_env="local")
    assert_production_secrets_configured(s)


def test_production_rejects_default_jwt_secret() -> None:
    s = Settings(
        app_env="production",
        jwt_secret=SecretStr("change-me-to-32-chars-min-secret-please"),
        tg_bot_token=SecretStr("not-empty-bot-token-xxxxxxxx"),
        tg_webhook_secret=SecretStr("webhook-secret"),
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        assert_production_secrets_configured(s)


def test_production_rejects_empty_bot_token() -> None:
    s = Settings(
        app_env="production",
        jwt_secret=SecretStr("unique-jwt-secret-at-least-32-chars-long-ok"),
        tg_bot_token=SecretStr(""),
        tg_webhook_secret=SecretStr("webhook-secret"),
    )
    with pytest.raises(RuntimeError, match="TG_BOT_TOKEN"):
        assert_production_secrets_configured(s)


def test_production_rejects_empty_webhook_secret() -> None:
    s = Settings(
        app_env="production",
        jwt_secret=SecretStr("unique-jwt-secret-at-least-32-chars-long-ok"),
        tg_bot_token=SecretStr("1234567890:ABCDEF"),
        tg_webhook_secret=SecretStr(""),
    )
    with pytest.raises(RuntimeError, match="TG_WEBHOOK_SECRET"):
        assert_production_secrets_configured(s)


def test_production_accepts_configured_secrets() -> None:
    s = Settings(
        app_env="production",
        jwt_secret=SecretStr("unique-jwt-secret-at-least-32-chars-long-ok"),
        tg_bot_token=SecretStr("1234567890:ABCDEF"),
        tg_webhook_secret=SecretStr("webhook-secret"),
    )
    assert_production_secrets_configured(s)
