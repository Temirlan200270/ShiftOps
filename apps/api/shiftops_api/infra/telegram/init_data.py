"""Telegram Mini App ``initData`` validation.

Reference:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Implemented from scratch (rather than pulling a 3rd-party lib) for two reasons:
its 30 LOC, and we need fine-grained control over the auth_date window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

_DEFAULT_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    is_premium: bool


@dataclass(frozen=True, slots=True)
class ValidatedInitData:
    user: TelegramUser
    auth_date: datetime
    raw: dict[str, str]
    start_param: str | None


class InvalidInitData(Exception):
    """Validation failed — bad signature, missing fields, or replay."""


class InitDataValidator:
    """HMAC-SHA256 validation of Telegram initData strings.

    Construct once per bot token at startup, then call :meth:`validate`.
    """

    def __init__(self, bot_token: str, max_age: timedelta = _DEFAULT_MAX_AGE) -> None:
        if not bot_token:
            raise ValueError("bot_token must not be empty")
        self._bot_token = bot_token
        self._max_age = max_age
        self._secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

    def validate(self, init_data: str, *, now: datetime | None = None) -> ValidatedInitData:
        if not init_data:
            raise InvalidInitData("empty init_data")

        # 1. Parse query string preserving order, then pop hash.
        pairs = parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)

        provided_hash = data.pop("hash", None)
        if not provided_hash:
            raise InvalidInitData("hash missing")

        # 2. Build data_check_string: sorted "key=value" lines joined with \n.
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items())
        )

        # 3. HMAC-SHA256 with secret_key derived above.
        expected = hmac.new(
            key=self._secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, provided_hash):
            raise InvalidInitData("hash mismatch")

        # 4. auth_date freshness.
        auth_date_raw = data.get("auth_date")
        if not auth_date_raw or not auth_date_raw.isdigit():
            raise InvalidInitData("auth_date missing or invalid")
        auth_date = datetime.fromtimestamp(int(auth_date_raw), tz=UTC)
        now_utc = now or datetime.now(tz=UTC)
        if now_utc - auth_date > self._max_age:
            raise InvalidInitData("auth_date too old")
        if auth_date - now_utc > timedelta(minutes=5):
            raise InvalidInitData("auth_date in the future")

        # 5. Decode user payload (JSON-encoded inside the form).
        user_raw = data.get("user")
        if not user_raw:
            raise InvalidInitData("user missing")
        try:
            user_dict: dict[str, Any] = json.loads(user_raw)
        except json.JSONDecodeError as exc:
            raise InvalidInitData("user is not valid JSON") from exc

        try:
            user = TelegramUser(
                id=int(user_dict["id"]),
                first_name=str(user_dict.get("first_name", "")),
                last_name=user_dict.get("last_name"),
                username=user_dict.get("username"),
                language_code=user_dict.get("language_code"),
                is_premium=bool(user_dict.get("is_premium", False)),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidInitData(f"user payload invalid: {exc}") from exc

        return ValidatedInitData(
            user=user,
            auth_date=auth_date,
            raw=data,
            start_param=data.get("start_param"),
        )

    @staticmethod
    def build_init_data(bot_token: str, payload: dict[str, str]) -> str:
        """Test helper: produce a signed init_data string for a payload.

        Not used in production — only for unit tests.
        """
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(payload.items())
        )
        signature = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        from urllib.parse import urlencode

        return urlencode({**payload, "hash": signature})
