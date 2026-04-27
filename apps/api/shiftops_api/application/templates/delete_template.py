"""Soft-fail-on-references delete for templates.

Why we don't allow deleting in-use templates
--------------------------------------------
``shifts.template_id`` has ``ondelete=RESTRICT`` (see
``infra/db/models/shift.py``). Postgres would raise an integrity error if
we attempted a cascade. Surfacing that as ``409 in_use`` is friendlier than
500 + log scrape, and lets the UI suggest "rename it instead, or close
existing shifts first".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Shift, Template


@dataclass(frozen=True, slots=True)
class DeletedTemplate:
    template_id: uuid.UUID


class DeleteTemplateUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self, *, user: CurrentUser, template_id: uuid.UUID
    ) -> Result[DeletedTemplate, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        template = (
            await self._session.execute(select(Template).where(Template.id == template_id))
        ).scalar_one_or_none()
        if template is None:
            return Failure(DomainError("template_not_found"))

        in_use = (
            await self._session.execute(
                select(func.count())
                .select_from(Shift)
                .where(Shift.template_id == template_id)
            )
        ).scalar_one()
        if int(in_use or 0) > 0:
            return Failure(
                DomainError(
                    "template_in_use",
                    details={"shifts_count": str(in_use)},
                )
            )

        await self._session.delete(template)
        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="template.deleted",
            payload={"template_id": str(template_id)},
        )
        await self._session.commit()
        return Success(DeletedTemplate(template_id=template_id))
