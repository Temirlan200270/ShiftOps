"""List all templates in the current organization with task counts."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.templates.dtos import TemplateListItemDTO
from shiftops_api.domain.result import DomainError, Result, Success
from shiftops_api.infra.db.models import Template, TemplateTask


class ListTemplatesUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, user: CurrentUser) -> Result[list[TemplateListItemDTO], DomainError]:
        # RLS already filters templates to the caller's org via the GUC,
        # so we don't add a redundant WHERE on organization_id here. That
        # keeps this query identical for owners and admins.
        del user  # explicitly unused — present for symmetry / RBAC hooks

        stmt = (
            select(
                Template.id,
                Template.name,
                Template.role_target,
                func.count(TemplateTask.id).label("task_count"),
            )
            .outerjoin(TemplateTask, TemplateTask.template_id == Template.id)
            .group_by(Template.id, Template.name, Template.role_target)
            .order_by(Template.name.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return Success(
            [
                TemplateListItemDTO(
                    id=row.id,
                    name=row.name,
                    role_target=row.role_target,
                    task_count=int(row.task_count or 0),
                )
                for row in rows
            ]
        )


__all__ = ["ListTemplatesUseCase"]
