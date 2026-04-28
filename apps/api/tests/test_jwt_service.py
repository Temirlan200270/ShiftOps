"""Unit tests for the JWT service."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from freezegun import freeze_time

from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.auth.jwt_service import JwtError, JwtService

SECRET = "test-secret-must-be-long-enough-32ch"


def test_round_trip_access_token() -> None:
    svc = JwtService(secret=SECRET, access_ttl_seconds=60, refresh_ttl_seconds=600)
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = svc.mint_access(user_id=user_id, org_id=org_id, role=UserRole.OPERATOR, tg_user_id=42)

    payload = svc.verify(token)
    assert payload.sub == user_id
    assert payload.org == org_id
    assert payload.role is UserRole.OPERATOR
    assert payload.tg == 42
    assert payload.token_type == "access"


def test_refresh_token_marks_typ() -> None:
    svc = JwtService(secret=SECRET)
    token = svc.mint_refresh(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.OWNER)
    assert svc.verify(token).token_type == "refresh"


def test_expired_token_rejected() -> None:
    svc = JwtService(secret=SECRET, access_ttl_seconds=1, refresh_ttl_seconds=1)
    with freeze_time("2026-04-27 00:00:00"):
        token = svc.mint_access(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.ADMIN)
    with freeze_time("2026-04-27 00:00:00") as frozen:
        frozen.tick(delta=timedelta(seconds=120))
        with pytest.raises(JwtError):
            svc.verify(token)


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError):
        JwtService(secret="short")


def test_verify_refresh_only_rejects_access_token() -> None:
    svc = JwtService(secret=SECRET)
    token = svc.mint_access(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.OPERATOR)
    with pytest.raises(JwtError):
        svc.verify_refresh_only(token)


def test_verify_refresh_only_accepts_refresh() -> None:
    svc = JwtService(secret=SECRET)
    token = svc.mint_refresh(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.OWNER)
    payload = svc.verify_refresh_only(token)
    assert payload.token_type == "refresh"


def test_tampered_token_rejected() -> None:
    svc = JwtService(secret=SECRET)
    token = svc.mint_access(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role=UserRole.OPERATOR)
    tampered = token[:-2] + ("XX" if not token.endswith("XX") else "YY")
    with pytest.raises(JwtError):
        svc.verify(tampered)
