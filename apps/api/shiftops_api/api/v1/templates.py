"""Template management — admin and owner only.

Operators receive 403 from ``require_role``. The endpoints intentionally do
not surface the operator's own assignment-time view; that lives on
``GET /v1/shifts/me``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.templates.delete_template import DeleteTemplateUseCase
from shiftops_api.application.templates.dtos import TemplateInputDTO, TemplateTaskInputDTO
from shiftops_api.application.templates.get_template import GetTemplateUseCase
from shiftops_api.application.templates.list_templates import ListTemplatesUseCase
from shiftops_api.application.templates.save_template import SaveTemplateUseCase
from shiftops_api.domain.enums import Criticality, UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


class TemplateTaskIn(BaseModel):
    """Inbound task; ``id`` is optional for new ones."""

    id: UUID | None = None
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    criticality: Criticality
    requires_photo: bool = False
    requires_comment: bool = False


class TemplateIn(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    role_target: UserRole
    tasks: list[TemplateTaskIn] = Field(min_length=1, max_length=200)


class TemplateTaskOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    criticality: str
    requires_photo: bool
    requires_comment: bool
    order_index: int


class TemplateOut(BaseModel):
    id: UUID
    name: str
    role_target: str
    tasks: list[TemplateTaskOut]


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
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        role_target=tpl.role_target,
        tasks=[
            TemplateTaskOut(
                id=t.id,
                title=t.title,
                description=t.description,
                criticality=t.criticality,
                requires_photo=t.requires_photo,
                requires_comment=t.requires_comment,
                order_index=t.order_index,
            )
            for t in tpl.tasks
        ],
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
    use_case = SaveTemplateUseCase(session=session)
    result = await use_case.execute(
        user=user,
        template_id=None,
        payload=_to_input_dto(payload),
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    assert isinstance(result, Success)
    return TemplateSaveResponse(id=result.value.template_id)


@router.put("/{template_id}", response_model=TemplateSaveResponse)
async def update_template(
    template_id: UUID,
    payload: TemplateIn,
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> TemplateSaveResponse:
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
    return TemplateSaveResponse(id=result.value.template_id)


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
                criticality=t.criticality,
                requires_photo=t.requires_photo,
                requires_comment=t.requires_comment,
            )
            for t in payload.tasks
        ],
    )
