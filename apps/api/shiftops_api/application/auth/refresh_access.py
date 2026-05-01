"""Use-case: mint a new access JWT from a valid refresh JWT.

Refresh tokens are bearer credentials; verification does not rely on tenant RLS
until we've decoded claims. Then we set ``app.org_id`` like :func:`require_user`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.auth.jwt_service import JwtError, JwtService
from shiftops_api.infra.db.models import Organization
from shiftops_api.infra.db.models import User as UserModel
from shiftops_api.infra.db.rls import set_org_guc


@dataclass(frozen=True, slots=True)
class RefreshSuccess:
    access_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class RefreshFailure:
    reason: str


RefreshResult = RefreshSuccess | RefreshFailure


class RefreshAccessUseCase:
    def __init__(self, session: AsyncSession, jwt: JwtService | None = None) -> None:
        self._session = session
        self._jwt = jwt or JwtService()

    async def execute(self, refresh_token: str) -> RefreshResult:
        try:
            payload = self._jwt.verify_refresh_only(refresh_token)
        except JwtError as exc:
            return RefreshFailure(reason=f"invalid_refresh_token: {exc}")

        await set_org_guc(self._session, organization_id=payload.org)

        user = await self._session.get(UserModel, payload.sub)
        if user is None or user.organization_id != payload.org:
            return RefreshFailure(reason="user_not_found")

        if not user.is_active:
            return RefreshFailure(reason="user_inactive")

        org = await self._session.get(Organization, user.organization_id)
        if org is None or org.deleted_at is not None or not org.is_active:
            return RefreshFailure(reason="organization_unavailable")

        access = self._jwt.mint_access(
            user_id=user.id,
            org_id=user.organization_id,
            role=UserRole(user.role),
            tg_user_id=payload.tg,
        )
        settings = get_settings()
        return RefreshSuccess(access_token=access, expires_in=settings.jwt_access_ttl_seconds)
