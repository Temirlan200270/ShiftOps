"""Unit tests for Telegram initData HMAC validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from shiftops_api.infra.telegram.init_data import (
    InitDataValidator,
    InvalidInitData,
)

BOT_TOKEN = "1234567890:TEST_TOKEN_FOR_HMAC_VALIDATION_xx"


def _signed_init_data(payload: dict[str, str], token: str = BOT_TOKEN) -> str:
    return InitDataValidator.build_init_data(token, payload)


def _user_payload() -> str:
    return json.dumps(
        {"id": 100500, "first_name": "Ivan", "username": "ivan_test", "language_code": "ru"}
    )


def test_validate_accepts_fresh_signed_payload() -> None:
    auth_date = int(datetime.now(tz=UTC).timestamp())
    init_data = _signed_init_data(
        {
            "auth_date": str(auth_date),
            "query_id": "AAH_test",
            "user": _user_payload(),
        }
    )

    validated = InitDataValidator(BOT_TOKEN).validate(init_data)
    assert validated.user.id == 100500
    assert validated.user.username == "ivan_test"


def test_validate_rejects_tampered_hash() -> None:
    auth_date = int(datetime.now(tz=UTC).timestamp())
    init_data = _signed_init_data({"auth_date": str(auth_date), "user": _user_payload()})
    tampered = init_data.replace("Ivan", "Mallory")

    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate(tampered)


def test_validate_rejects_wrong_token() -> None:
    auth_date = int(datetime.now(tz=UTC).timestamp())
    init_data = _signed_init_data({"auth_date": str(auth_date), "user": _user_payload()})

    other_token = "9999999999:DIFFERENT_TOKEN_FOR_HMAC_VALIDATION"
    with pytest.raises(InvalidInitData):
        InitDataValidator(other_token).validate(init_data)


def test_validate_rejects_replay_after_24h() -> None:
    old = datetime.now(tz=UTC) - timedelta(hours=25)
    init_data = _signed_init_data(
        {"auth_date": str(int(old.timestamp())), "user": _user_payload()}
    )

    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate(init_data)


def test_validate_rejects_future_auth_date() -> None:
    future = datetime.now(tz=UTC) + timedelta(minutes=10)
    init_data = _signed_init_data(
        {"auth_date": str(int(future.timestamp())), "user": _user_payload()}
    )

    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate(init_data)


def test_validate_rejects_missing_user() -> None:
    auth_date = int(datetime.now(tz=UTC).timestamp())
    init_data = _signed_init_data({"auth_date": str(auth_date)})

    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate(init_data)


def test_validate_rejects_empty() -> None:
    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate("")


def test_validate_rejects_no_hash_field() -> None:
    raw = urlencode({"auth_date": "0", "user": _user_payload()})
    with pytest.raises(InvalidInitData):
        InitDataValidator(BOT_TOKEN).validate(raw)
