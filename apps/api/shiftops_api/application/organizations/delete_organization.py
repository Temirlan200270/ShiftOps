"""Super-admin use case: permanently remove a tenant and all dependent rows.

PostgreSQL FK chains ``ON DELETE CASCADE`` from ``organizations`` into locations,
users, templates, shifts, invites, audit_events, etc. Shifts cascade to
task_instances and attachments. This is **irreversible** — exposed only via the
platform super-admin Telegram command.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization
from shiftops_api.infra.db.rls import enter_privileged_rls_mode

_log = structlog.get_logger("shiftops.org.delete")


@dataclass(frozen=True, slots=True)
class OrganizationDeleted:
    organization_id: uuid.UUID
    name: str


class DeleteOrganizationUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, organization_id: uuid.UUID) -> Result[OrganizationDeleted, DomainError]:
        await enter_privileged_rls_mode(self._session, reason="delete_organization")

        org = await self._session.get(Organization, organization_id)
        if org is None:
            return Failure(DomainError("organization_not_found", "organization does not exist"))

        name = org.name
        try:
            await self._session.delete(org)
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            _log.warning(
                "organization_delete_blocked",
                organization_id=str(organization_id),
                error=str(exc),
            )
            return Failure(
                DomainError(
                    "organization_delete_blocked",
                    "database refused delete — check for unexpected FK constraints",
                )
            )

        _log.info("organization_deleted", organization_id=str(organization_id), name=name)
        return Success(OrganizationDeleted(organization_id=organization_id, name=name))


__all__ = ["DeleteOrganizationUseCase", "OrganizationDeleted"]
