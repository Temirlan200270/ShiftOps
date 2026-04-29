"""Shift HTTP endpoints — start, list tasks, complete task, request waiver, close."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_user
from shiftops_api.application.shifts.close_shift import CloseShiftUseCase
from shiftops_api.application.shifts.complete_task import CompleteTaskUseCase
from shiftops_api.application.shifts.list_history import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListHistoryUseCase,
)
from shiftops_api.application.shifts.list_my_shift import ListMyShiftUseCase
from shiftops_api.application.shifts.request_waiver import RequestWaiverUseCase
from shiftops_api.application.shifts.start_shift import StartShiftUseCase
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import is_line_staff
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.storage.provider import get_storage_provider

router = APIRouter()


class ShiftSummary(BaseModel):
    id: UUID
    template_name: str
    status: str
    score: float | None
    progress_done: int
    progress_total: int
    scheduled_start: str
    scheduled_end: str
    actual_start: str | None
    actual_end: str | None


class TaskCard(BaseModel):
    id: UUID
    title: str
    description: str | None
    section: str | None = None
    criticality: str
    requires_photo: bool
    requires_comment: bool
    status: str
    comment: str | None
    has_attachment: bool
    completed_at: str | None


class CurrentShiftResponse(BaseModel):
    shift: ShiftSummary
    tasks: list[TaskCard]


class StartShiftResponse(BaseModel):
    shift_id: UUID


class CompleteTaskResponse(BaseModel):
    task_id: UUID
    status: str
    suspicious: bool = False


class ScoreBreakdown(BaseModel):
    """Each component is in [0, 1]; multiply by the weight column to get
    the points contribution (50/25/15/10). The TWA renders all four so the
    operator can see *why* their score is what it is."""

    completion: float
    critical_compliance: float
    timeliness: float
    photo_quality: float


class CloseShiftResponse(BaseModel):
    shift_id: UUID
    final_status: str
    score: float
    breakdown: ScoreBreakdown
    formula_version: int
    missed_required: int
    missed_critical: int


class HistoryRow(BaseModel):
    id: UUID
    template_name: str
    status: str
    score: float | None
    formula_version: int
    breakdown: ScoreBreakdown | None
    scheduled_start: str
    scheduled_end: str
    actual_start: str | None
    actual_end: str | None
    tasks_total: int
    tasks_done: int
    handover_summary: str | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryRow]
    next_cursor: str | None


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Closed-shift history for the current operator (or a target user when admin/owner)",
)
async def list_history(
    cursor: Annotated[
        datetime | None,
        Query(description="ISO timestamp from a previous response's next_cursor"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description=f"Max {MAX_PAGE_SIZE}"),
    ] = DEFAULT_PAGE_SIZE,
    user_id: Annotated[
        UUID | None,
        Query(description="Admin/owner only: scope to a specific operator."),
    ] = None,
    location_id: Annotated[
        UUID | None,
        Query(description="Filter by location."),
    ] = None,
    date_from: Annotated[
        date | None,
        Query(alias="from", description="Inclusive start date (UTC)."),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(alias="to", description="Inclusive end date (UTC)."),
    ] = None,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    # RBAC at the edge: line staff cannot peek at a teammate's history
    # via ?user_id=. The use case enforces the same rule, but rejecting
    # at the boundary keeps the audit trail honest (no DB roundtrip on
    # forbidden queries).
    if user_id is not None and is_line_staff(user.role) and user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    rf_dt: datetime | None = (
        datetime.combine(date_from, time.min, tzinfo=UTC) if date_from is not None else None
    )
    rt_dt: datetime | None = (
        datetime.combine(date_to, time.max, tzinfo=UTC) if date_to is not None else None
    )

    use_case = ListHistoryUseCase(session=session)
    result = await use_case.execute(
        user=user,
        cursor=cursor,
        limit=limit,
        target_user_id=user_id,
        location_id=location_id,
        date_from=rf_dt,
        date_to=rt_dt,
    )
    if isinstance(result, Failure):
        if result.error.code == "forbidden":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    assert isinstance(result, Success)
    page = result.value
    return HistoryResponse(
        items=[
            HistoryRow(
                id=row.id,
                template_name=row.template_name,
                status=row.status,
                score=float(row.score) if row.score is not None else None,
                formula_version=row.formula_version,
                breakdown=(
                    ScoreBreakdown(
                        completion=float(row.completion),
                        critical_compliance=float(row.critical_compliance),
                        timeliness=float(row.timeliness),
                        photo_quality=float(row.photo_quality),
                    )
                    if row.completion is not None
                    else None
                ),
                scheduled_start=row.scheduled_start.isoformat(),
                scheduled_end=row.scheduled_end.isoformat(),
                actual_start=row.actual_start.isoformat() if row.actual_start else None,
                actual_end=row.actual_end.isoformat() if row.actual_end else None,
                tasks_total=row.tasks_total,
                tasks_done=row.tasks_done,
                handover_summary=row.handover_summary,
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/me", response_model=CurrentShiftResponse)
async def get_my_shift(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CurrentShiftResponse:
    use_case = ListMyShiftUseCase(session=session)
    result = await use_case.execute(user=user)
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.error.code)
    assert isinstance(result, Success)
    return CurrentShiftResponse.model_validate(result.value, from_attributes=True)


@router.post("/{shift_id}/start", response_model=CurrentShiftResponse)
async def start_shift(
    shift_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CurrentShiftResponse:
    use_case = StartShiftUseCase(session=session)
    result = await use_case.execute(shift_id=shift_id, user=user)
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.error.code)
    assert isinstance(result, Success)

    # Return the updated current shift (same shape as GET /v1/shifts/me) to avoid
    # an extra round-trip on flaky connections.
    read_use_case = ListMyShiftUseCase(session=session)
    read_result = await read_use_case.execute(user=user)
    if isinstance(read_result, Failure):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=read_result.error.code)
    assert isinstance(read_result, Success)
    return CurrentShiftResponse.model_validate(read_result.value, from_attributes=True)


@router.post("/tasks/{task_id}/complete", response_model=CompleteTaskResponse)
async def complete_task(
    task_id: UUID,
    comment: str | None = Form(default=None),
    photo: UploadFile | None = File(default=None),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CompleteTaskResponse:
    settings = get_settings()
    use_case = CompleteTaskUseCase(
        session=session,
        storage=get_storage_provider(),
        phash_threshold=settings.antifake_phash_threshold,
        history_lookback=settings.antifake_history_lookback,
    )
    photo_bytes = await photo.read() if photo is not None else None
    photo_mime = photo.content_type if photo is not None else None
    result = await use_case.execute(
        task_id=task_id,
        user=user,
        photo_bytes=photo_bytes,
        photo_mime=photo_mime,
        comment=comment,
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    assert isinstance(result, Success)
    return CompleteTaskResponse(
        task_id=task_id,
        status=result.value.status,
        suspicious=result.value.suspicious,
    )


class WaiverRequest(BaseModel):
    reason: str
    description: str | None = None


@router.post("/tasks/{task_id}/waiver", status_code=status.HTTP_202_ACCEPTED)
async def request_waiver(
    task_id: UUID,
    payload: WaiverRequest,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    use_case = RequestWaiverUseCase(session=session)
    result = await use_case.execute(
        task_id=task_id,
        user=user,
        reason=payload.reason,
        description=payload.description,
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error.code)
    return {"status": "pending_approval"}


@router.post("/{shift_id}/close", response_model=CloseShiftResponse)
async def close_shift(
    shift_id: UUID,
    confirm_violations: bool = False,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CloseShiftResponse:
    use_case = CloseShiftUseCase(session=session)
    result = await use_case.execute(
        shift_id=shift_id,
        user=user,
        confirm_violations=confirm_violations,
    )
    if isinstance(result, Failure):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.error.code)
    assert isinstance(result, Success)
    closed = result.value
    return CloseShiftResponse(
        shift_id=closed.shift_id,
        final_status=closed.final_status,
        score=float(closed.score),
        breakdown=ScoreBreakdown(
            completion=float(closed.breakdown.completion),
            critical_compliance=float(closed.breakdown.critical_compliance),
            timeliness=float(closed.breakdown.timeliness),
            photo_quality=float(closed.breakdown.photo_quality),
        ),
        formula_version=closed.formula_version,
        missed_required=closed.missed_required,
        missed_critical=closed.missed_critical,
    )
