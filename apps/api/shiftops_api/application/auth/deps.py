"""FastAPI dependencies for authn / authz / tenant context.

The contract:

- :func:`require_user` parses the Bearer token, returns a :class:`CurrentUser`,
  and **also** sets `app.org_id` on the session so RLS policies kick in.
- :func:`require_role` enforces RBAC on top of that.

Sessions opened by :func:`shiftops_api.infra.db.engine.get_session` start with
no GUC set; without `app.org_id`, RLS-enabled tables will return zero rows —
exactly the safe default.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.auth.jwt_service import JwtError, JwtService
from shiftops_api.infra.db.engine import get_session

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    tg_user_id: int | None


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
        )
    try:
        payload = JwtService().verify(credentials.credentials)
    except JwtError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid_token: {exc}",
        ) from exc

    if payload.token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not_an_access_token",
        )

    # CRITICAL: set RLS context on this session before the handler runs any
    # query. Use set_config(..., true) instead of SET LOCAL ... = :param —
    # asyncpg cannot bind parameters in SET (syntax error at $1); set_config
    # is the supported parameterized equivalent of SET LOCAL for this tx.
    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(payload.org)},
    )
    return CurrentUser(
        id=payload.sub,
        organization_id=payload.org,
        role=payload.role,
        tg_user_id=payload.tg,
    )


def require_role(
    *allowed: UserRole,
) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    """Dependency factory enforcing role membership.

    Usage:

        @router.get("/", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.OWNER))])
    """

    async def _check(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient_role",
            )
        return user

    return _check
