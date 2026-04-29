"""Fail fast in production when critical secrets are missing or left at dev defaults."""

from __future__ import annotations

from shiftops_api.config import Settings

_DEFAULT_JWT_SECRET = "change-me-to-32-chars-min-secret-please"


def assert_production_secrets_configured(settings: Settings) -> None:
    """Raise ``RuntimeError`` if ``app_env=production`` but secrets are unsafe.

    Why: a mistaken ``fly secrets unset`` or empty override would otherwise let
    the API start with a known JWT signing key or without a bot token — anyone
    could mint tokens or the bot layer would be broken in subtle ways.
    """

    if settings.app_env != "production":
        return
    if settings.jwt_secret.get_secret_value() == _DEFAULT_JWT_SECRET:
        msg = "JWT_SECRET must be set to a non-default value in production"
        raise RuntimeError(msg)
    if not settings.tg_bot_token.get_secret_value().strip():
        msg = "TG_BOT_TOKEN must be set in production"
        raise RuntimeError(msg)
    if not settings.tg_webhook_secret.get_secret_value().strip():
        msg = "TG_WEBHOOK_SECRET must be set in production (Telegram webhook header)"
        raise RuntimeError(msg)
