"""Template management — admin and owner only.

Operators receive 403 from ``require_role``. The endpoints intentionally do
not surface the operator's own assignment-time view; that lives on
``GET /v1/shifts/me``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.templates.bulk_parser import (
    BulkParseError,
    parse_bulk_text,
    to_template_input,
)
from shiftops_api.application.templates.delete_template import DeleteTemplateUseCase
from shiftops_api.application.templates.dtos import TemplateInputDTO, TemplateTaskInputDTO
from shiftops_api.application.templates.get_template import GetTemplateUseCase
from shiftops_api.application.templates.list_templates import ListTemplatesUseCase
from shiftops_api.application.templates.recurrence import RecurrenceConfig
from shiftops_api.application.templates.save_template import SaveTemplateUseCase
from shiftops_api.domain.enums import Criticality, UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import Location, Template, User

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


class TemplateTaskIn(BaseModel):
    """Inbound task; ``id`` is optional for new ones."""

    id: UUID | None = None
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    section: str | None = Field(default=None, max_length=64)
    criticality: Criticality
    requires_photo: bool = False
    requires_comment: bool = False


class TemplateIn(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    role_target: UserRole
    tasks: list[TemplateTaskIn] = Field(min_length=1, max_length=200)
    # Optional recurrence config — when ``auto_create=true`` the worker
    # materialises a shift every day (or on the configured weekdays).
    # ``None`` keeps the column empty: nothing fires automatically.
    recurrence: RecurrenceConfig | None = None


class TemplateTaskOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    section: str | None
    criticality: str
    requires_photo: bool
    requires_comment: bool
    order_index: int


class TemplateOut(BaseModel):
    id: UUID
    name: str
    role_target: str
    tasks: list[TemplateTaskOut]
    recurrence: RecurrenceConfig | None = None


class TemplateListItemOut(BaseModel):
    id: UUID
    name: str
    role_target: str
    task_count: int


class TemplateSaveResponse(BaseModel):
    id: UUID


@router.get("", response_model=list[TemplateListItemOut])
async def list_templates(
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> list[TemplateListItemOut]:
    use_case = ListTemplatesUseCase(session=session)
    result = await use_case.execute(user=user)
    assert isinstance(result, Success)
    return [
        TemplateListItemOut(
            id=row.id,
            name=row.name,
            role_target=row.role_target,
            task_count=row.task_count,
        )
        for row in result.value
    ]


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: UUID,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    use_case = GetTemplateUseCase(session=session)
    result = await use_case.execute(user=user, template_id=template_id)
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.error.code)
    assert isinstance(result, Success)
    tpl = result.value

    # Recurrence config is stored on the row itself (JSONB). The use
    # case only returns task data, so we re-read the column here. It's
    # one row by primary key — cheap, and lets us keep the use case
    # focused on task lifecycle.
    template_row = await session.get(Template, template_id)
    recurrence = None
    if template_row is not None and template_row.default_schedule:
        try:
            recurrence = RecurrenceConfig.model_validate(template_row.default_schedule)
        except Exception:  # noqa: BLE001 — bad blob renders as "no recurrence"
            recurrence = None

    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        role_target=tpl.role_target,
        tasks=[
            TemplateTaskOut(
                id=t.id,
                title=t.title,
                description=t.description,
                section=t.section,
                criticality=t.criticality,
                requires_photo=t.requires_photo,
                requires_comment=t.requires_comment,
                order_index=t.order_index,
            )
            for t in tpl.tasks
        ],
        recurrence=recurrence,
    )


@router.post(
    "",
    response_model=TemplateSaveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: TemplateIn,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> TemplateSaveResponse:
    if payload.recurrence is not None:
        await _validate_recurrence(session=session, user=user, payload=payload)

    use_case = SaveTemplateUseCase(session=session)
    result = await use_case.execute(
        user=user,
        template_id=None,
        payload=_to_input_dto(payload),
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    assert isinstance(result, Success)

    await _persist_recurrence(session, user, result.value.template_id, payload.recurrence)
    return TemplateSaveResponse(id=result.value.template_id)


@router.put("/{template_id}", response_model=TemplateSaveResponse)
async def update_template(
    template_id: UUID,
    payload: TemplateIn,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> TemplateSaveResponse:
    if payload.recurrence is not None:
        await _validate_recurrence(session=session, user=user, payload=payload)

    use_case = SaveTemplateUseCase(session=session)
    result = await use_case.execute(
        user=user,
        template_id=template_id,
        payload=_to_input_dto(payload),
    )
    if isinstance(result, Failure):
        # 404 for "doesn't exist", 400 for everything else.
        code = result.error.code
        http_status = (
            status.HTTP_404_NOT_FOUND
            if code == "template_not_found"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=http_status, detail=code)
    assert isinstance(result, Success)

    await _persist_recurrence(session, user, template_id, payload.recurrence)
    return TemplateSaveResponse(id=result.value.template_id)


async def _validate_recurrence(
    *,
    session: AsyncSession,
    user: CurrentUser,
    payload: TemplateIn,
) -> None:
    """Ensure ``recurrence.location_id`` and ``default_assignee_id`` belong
    to the actor's organization. RLS would already reject other-org rows
    on read, but we want a 400 with a useful code, not silent NULLs.
    """

    cfg = payload.recurrence
    if cfg is None:
        return

    location = (
        await session.execute(
            select(Location.id)
            .where(Location.id == cfg.location_id)
            .where(Location.organization_id == user.organization_id)
        )
    ).first()
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="recurrence_location_not_found",
        )

    if cfg.default_assignee_id is not None:
        assignee = (
            await session.execute(
                select(User.id, User.role, User.is_active)
                .where(User.id == cfg.default_assignee_id)
                .where(User.organization_id == user.organization_id)
            )
        ).first()
        if assignee is None or not assignee.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="recurrence_assignee_not_found",
            )
        # The assignee should be capable of running this checklist —
        # admin templates → admin/owner; bartender → bartender/admin/owner;
        # operator (and owner-target) templates → any active member.
        if payload.role_target == UserRole.ADMIN and assignee.role not in (
            UserRole.ADMIN.value,
            UserRole.OWNER.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="recurrence_assignee_role_mismatch",
            )
        if payload.role_target == UserRole.BARTENDER and assignee.role not in (
            UserRole.BARTENDER.value,
            UserRole.ADMIN.value,
            UserRole.OWNER.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="recurrence_assignee_role_mismatch",
            )


async def _persist_recurrence(
    session: AsyncSession,
    user: CurrentUser,
    template_id: UUID,
    recurrence: RecurrenceConfig | None,
) -> None:
    """Update the JSONB ``default_schedule`` cell after the template
    save has committed.

    SaveTemplateUseCase ends its transaction inside the use case, which
    drops the request's ``SET LOCAL app.org_id`` GUC. We re-apply it
    here so RLS still scopes the lookup to the actor's tenant.
    """

    if recurrence is None:
        # We still want to clear the column on update if the caller
        # turned recurrence off.
        await session.execute(
            text("SELECT set_config('app.org_id', :oid, true)"),
            {"oid": str(user.organization_id)},
        )
        template = await session.get(Template, template_id)
        if template is None:
            return
        template.default_schedule = None
        await session.commit()
        return

    await session.execute(
        text("SELECT set_config('app.org_id', :oid, true)"),
        {"oid": str(user.organization_id)},
    )
    template = await session.get(Template, template_id)
    if template is None:
        return
    template.default_schedule = recurrence.to_storage()
    await session.commit()


class TemplateImportIn(BaseModel):
    """Bulk-import payload: free-form Markdown-ish checklist text."""

    name: str = Field(min_length=3, max_length=128)
    role_target: UserRole
    content: str = Field(min_length=1, max_length=20_000)


class ParsedTaskOut(BaseModel):
    title: str
    description: str | None
    section: str | None
    criticality: str
    requires_photo: bool
    requires_comment: bool


class TemplateImportPreviewOut(BaseModel):
    """Returned when ``dry_run=true``: caller renders a side panel."""

    sections: list[str]
    tasks: list[ParsedTaskOut]
    errors: list[dict[str, str]]


class TemplateImportApplyOut(BaseModel):
    template_id: UUID
    sections: list[str]
    task_count: int
    parse_errors: list[dict[str, str]]


@router.post(
    "/import",
    summary="Bulk-import a template from Markdown-ish text",
    response_model=None,
)
async def import_template(
    payload: TemplateImportIn,
    dry_run: bool = False,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> TemplateImportPreviewOut | TemplateImportApplyOut:
    parsed, parse_errors = parse_bulk_text(payload.content)

    # Hard parser failures (no tasks at all) are 400 even on dry_run so
    # the UI surfaces "fix your text" before the user clicks Apply.
    if not parsed.tasks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=parse_errors[0].code if parse_errors else "no_tasks_found",
        )

    if dry_run:
        return TemplateImportPreviewOut(
            sections=parsed.sections,
            tasks=[
                ParsedTaskOut(
                    title=t.title,
                    description=t.description,
                    section=t.section,
                    criticality=t.criticality.value,
                    requires_photo=t.requires_photo,
                    requires_comment=t.requires_comment,
                )
                for t in parsed.tasks
            ],
            errors=[_err_to_dict(e) for e in parse_errors],
        )

    use_case = SaveTemplateUseCase(session=session)
    result = await use_case.execute(
        user=user,
        template_id=None,
        payload=to_template_input(parsed, name=payload.name, role_target=payload.role_target),
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    assert isinstance(result, Success)
    return TemplateImportApplyOut(
        template_id=result.value.template_id,
        sections=parsed.sections,
        task_count=len(parsed.tasks),
        parse_errors=[_err_to_dict(e) for e in parse_errors],
    )


def _err_to_dict(err: BulkParseError) -> dict[str, str]:
    return {"code": err.code, "message": err.message}


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    use_case = DeleteTemplateUseCase(session=session)
    result = await use_case.execute(user=user, template_id=template_id)
    if isinstance(result, Failure):
        code = result.error.code
        if code == "template_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
        if code == "template_in_use":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_input_dto(payload: TemplateIn) -> TemplateInputDTO:
    return TemplateInputDTO(
        name=payload.name,
        role_target=payload.role_target,
        tasks=[
            TemplateTaskInputDTO(
                id=t.id,
                title=t.title,
                description=t.description,
                section=t.section,
                criticality=t.criticality,
                requires_photo=t.requires_photo,
                requires_comment=t.requires_comment,
            )
            for t in payload.tasks
        ],
    )
