"""Create-or-update a template in one atomic transaction.

Why one use case for both
-------------------------
The HTTP wrapper for create vs update is trivial; the business logic is
identical (validate, replace tasks, audit). Splitting the use case makes
the SQL drift over time. We keep it as one and let the router dispatch
based on whether ``template_id`` is None.

Audit
-----
Each save writes one ``template.created`` or ``template.updated`` event so
admin actions are traceable. Tasks within the template are NOT individually
audited — the whole-template snapshot in the event payload is sufficient
for forensic purposes and keeps the audit log readable.

Validation
----------
- ``name`` 3..128 chars, trimmed.
- 1..200 tasks (sanity ceiling).
- Each task title 3..255 chars, trimmed.
- Re-using an existing ``task.id`` from another template is rejected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.templates.dtos import TemplateInputDTO
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Template, TemplateTask

MIN_TASKS = 1
MAX_TASKS = 200
MIN_NAME_LEN = 3
MAX_NAME_LEN = 128
MIN_TITLE_LEN = 3
MAX_TITLE_LEN = 255


@dataclass(frozen=True, slots=True)
class SavedTemplate:
    template_id: uuid.UUID


class SaveTemplateUseCase:
    """Authorization: admin or owner only. Operators are 403'd at the router."""

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        template_id: uuid.UUID | None,
        payload: TemplateInputDTO,
    ) -> Result[SavedTemplate, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        validation_error = _validate(payload)
        if validation_error is not None:
            return Failure(validation_error)

        if template_id is None:
            template = Template(
                organization_id=user.organization_id,
                name=payload.name.strip(),
                role_target=payload.role_target.value,
            )
            self._session.add(template)
            await self._session.flush()  # populates template.id
            event_type = "template.created"
        else:
            template = (
                await self._session.execute(
                    select(Template).where(Template.id == template_id)
                )
            ).scalar_one_or_none()
            if template is None:
                return Failure(DomainError("template_not_found"))
            template.name = payload.name.strip()
            template.role_target = payload.role_target.value
            event_type = "template.updated"

        # Replace tasks. We diff: keep ids the caller mentioned (for FK
        # provenance), delete the rest. New tasks get fresh ids assigned by
        # the DB. This is simpler than a per-task PATCH and gives the UI an
        # all-or-nothing update path.
        retained_ids = {
            t.id for t in payload.tasks if t.id is not None
        }
        existing = (
            (
                await self._session.execute(
                    select(TemplateTask).where(TemplateTask.template_id == template.id)
                )
            )
            .scalars()
            .all()
        )

        # Reject "stealing" a task from another template via id collision.
        if retained_ids:
            cross_org = (
                (
                    await self._session.execute(
                        select(TemplateTask).where(
                            TemplateTask.id.in_(retained_ids),
                            TemplateTask.template_id != template.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if cross_org:
                return Failure(DomainError("task_id_belongs_to_other_template"))

        existing_by_id = {t.id: t for t in existing}
        for old in existing:
            if old.id not in retained_ids:
                await self._session.delete(old)

        for index, task in enumerate(payload.tasks):
            description = task.description.strip() if task.description else None
            section = task.section.strip() if task.section else None
            if section == "":
                section = None
            if task.id is not None and task.id in existing_by_id:
                row = existing_by_id[task.id]
                row.title = task.title.strip()
                row.description = description
                row.section = section
                row.criticality = task.criticality.value
                row.requires_photo = task.requires_photo
                row.requires_comment = task.requires_comment
                row.order_index = index
            else:
                self._session.add(
                    TemplateTask(
                        template_id=template.id,
                        title=task.title.strip(),
                        description=description,
                        section=section,
                        criticality=task.criticality.value,
                        requires_photo=task.requires_photo,
                        requires_comment=task.requires_comment,
                        order_index=index,
                    )
                )

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type=event_type,
            payload={
                "template_id": str(template.id),
                "name": template.name,
                "role_target": template.role_target,
                "task_count": len(payload.tasks),
                "at": datetime.now(tz=UTC).isoformat(),
            },
        )

        await self._session.commit()
        return Success(SavedTemplate(template_id=template.id))


def _validate(payload: TemplateInputDTO) -> DomainError | None:
    name = payload.name.strip()
    if not (MIN_NAME_LEN <= len(name) <= MAX_NAME_LEN):
        return DomainError("invalid_name_length")
    if not (MIN_TASKS <= len(payload.tasks) <= MAX_TASKS):
        return DomainError("invalid_task_count")
    seen_ids: set[uuid.UUID] = set()
    for task in payload.tasks:
        title = task.title.strip()
        if not (MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN):
            return DomainError("invalid_task_title")
        if task.id is not None:
            if task.id in seen_ids:
                return DomainError("duplicate_task_id")
            seen_ids.add(task.id)
    return None
