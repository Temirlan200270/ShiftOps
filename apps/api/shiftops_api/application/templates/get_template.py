"""Fetch one template with its tasks ordered by order_index."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.templates.dtos import TemplateDTO, TemplateTaskDTO
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Template, TemplateTask


class GetTemplateUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self, *, user: CurrentUser, template_id: uuid.UUID
    ) -> Result[TemplateDTO, DomainError]:
        del user

        template = (
            await self._session.execute(select(Template).where(Template.id == template_id))
        ).scalar_one_or_none()
        if template is None:
            return Failure(DomainError("template_not_found"))

        tasks = (
            (
                await self._session.execute(
                    select(TemplateTask)
                    .where(TemplateTask.template_id == template_id)
                    .order_by(TemplateTask.order_index.asc())
                )
            )
            .scalars()
            .all()
        )
        return Success(
            TemplateDTO(
                id=template.id,
                name=template.name,
                role_target=template.role_target,
                tasks=[
                    TemplateTaskDTO(
                        id=t.id,
                        title=t.title,
                        description=t.description,
                        section=t.section,
                        criticality=t.criticality,
                        requires_photo=t.requires_photo,
                        requires_comment=t.requires_comment,
                        order_index=t.order_index,
                    )
                    for t in tasks
                ],
            )
        )
