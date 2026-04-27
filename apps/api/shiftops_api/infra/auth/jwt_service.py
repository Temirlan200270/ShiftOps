"""JWT minting and verification.

HS256 is appropriate here because the only consumer of these tokens is our
own backend; there is no third party we need RS256 for. If we ever expose
public APIs, we revisit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole

_ALGORITHM = "HS256"
_ISSUER = "shiftops"


@dataclass(frozen=True, slots=True)
class JwtPayload:
    sub: uuid.UUID
    org: uuid.UUID
    role: UserRole
    tg: int | None
    iat: datetime
    exp: datetime
    token_type: str  # "access" | "refresh"


class JwtError(Exception):
    pass


class JwtService:
    """Wraps `python-jose` so the rest of the app speaks domain types only."""

    def __init__(
        self,
        secret: str | None = None,
        access_ttl_seconds: int | None = None,
        refresh_ttl_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self._secret = secret or settings.jwt_secret.get_secret_value()
        if len(self._secret) < 32:
            raise ValueError("JWT secret must be at least 32 bytes")
        self._access_ttl = access_ttl_seconds or settings.jwt_access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds or settings.jwt_refresh_ttl_seconds

    def mint_access(
        self,
        *,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        role: UserRole,
        tg_user_id: int | None = None,
    ) -> str:
        return self._mint(
            user_id=user_id,
            org_id=org_id,
            role=role,
            tg_user_id=tg_user_id,
            ttl=self._access_ttl,
            token_type="access",
        )

    def mint_refresh(
        self,
        *,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        role: UserRole,
        tg_user_id: int | None = None,
    ) -> str:
        return self._mint(
            user_id=user_id,
            org_id=org_id,
            role=role,
            tg_user_id=tg_user_id,
            ttl=self._refresh_ttl,
            token_type="refresh",
        )

    def verify(self, token: str) -> JwtPayload:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=_ISSUER,
            )
        except JWTError as exc:
            raise JwtError(str(exc)) from exc

        try:
            return JwtPayload(
                sub=uuid.UUID(claims["sub"]),
                org=uuid.UUID(claims["org"]),
                role=UserRole(claims["role"]),
                tg=int(claims["tg"]) if claims.get("tg") is not None else None,
                iat=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
                exp=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
                token_type=claims.get("typ", "access"),
            )
        except (KeyError, ValueError) as exc:
            raise JwtError(f"malformed claims: {exc}") from exc

    def _mint(
        self,
        *,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        role: UserRole,
        tg_user_id: int | None,
        ttl: int,
        token_type: str,
    ) -> str:
        now = datetime.now(tz=UTC)
        claims: dict[str, str | int] = {
            "iss": _ISSUER,
            "sub": str(user_id),
            "org": str(org_id),
            "role": role.value,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            "typ": token_type,
        }
        if tg_user_id is not None:
            claims["tg"] = tg_user_id
        return jwt.encode(claims, self._secret, algorithm=_ALGORITHM)
