"""Shift HTTP endpoints — start, list tasks, complete task, request waiver, close."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.api.domain_http import raise_for_domain_failure
from shiftops_api.application.auth.deps import CurrentUser, require_user
from shiftops_api.application.shifts.claim_shift import ClaimShiftUseCase
from shiftops_api.application.shifts.close_shift import CloseShiftUseCase
from shiftops_api.application.shifts.complete_task import CompleteTaskUseCase
from shiftops_api.application.shifts.list_available_shifts import ListAvailableShiftsUseCase
from shiftops_api.application.shifts.list_history import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListHistoryUseCase,
)
from shiftops_api.application.shifts.list_my_scheduled import ListMyScheduledShiftsUseCase
from shiftops_api.application.shifts.list_my_shift import ListMyShiftUseCase
from shiftops_api.application.shifts.request_waiver import RequestWaiverUseCase
from shiftops_api.application.shifts.start_shift import StartShiftUseCase
from shiftops_api.application.shifts.swap_link_preview import SwapLinkPreviewUseCase
from shiftops_api.application.shifts.swap_shift_requests import (
    AcceptSwapShiftRequestUseCase,
    CancelSwapShiftRequestUseCase,
    CreateSwapShiftRequestUseCase,
    DeclineSwapShiftRequestUseCase,
    ListSwapShiftRequestsUseCase,
)
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
    operator_full_name: str
    slot_index: int
    station_label: str | None = None


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


class StartShiftIn(BaseModel):
    """Optional client geolocation from the TWA (best-effort audit beacon)."""

    client_latitude: float | None = None
    client_longitude: float | None = None
    client_accuracy_m: float | None = None


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


class CloseShiftIn(BaseModel):
    """Body for POST /shifts/{id}/close (optional — defaults match legacy query-only clients)."""

    confirm_violations: bool = False
    delay_reason: str | None = None


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
    slot_index: int
    station_label: str | None = None
    delay_reason: str | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryRow]
    next_cursor: str | None


class VacantShiftOut(BaseModel):
    id: UUID
    template_name: str
    template_id: UUID
    role_target: str
    location_id: UUID
    location_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int


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
    slot_index: Annotated[
        int | None,
        Query(ge=0, description="Filter by slot index (multi-post templates)."),
    ] = None,
    station_label: Annotated[
        str | None,
        Query(max_length=64, description="Exact match on station_label."),
    ] = None,
    station_label_empty: Annotated[
        bool,
        Query(
            description="When true, only shifts with no station_label (NULL). "
            "Ignored when a non-empty station_label is sent.",
        ),
    ] = False,
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
        slot_index=slot_index,
        station_label=station_label.strip() if station_label else None,
        station_label_empty=station_label_empty and not (station_label and station_label.strip()),
    )
    if isinstance(result, Failure):
        if result.error.code == "forbidden":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        raise_for_domain_failure(result)
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
                slot_index=row.slot_index,
                station_label=row.station_label,
                delay_reason=row.delay_reason,
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/available", response_model=list[VacantShiftOut])
async def list_available_shifts(
    location_id: Annotated[
        UUID | None,
        Query(description="Filter by location within the organization."),
    ] = None,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[VacantShiftOut]:
    use_case = ListAvailableShiftsUseCase(session=session)
    result = await use_case.execute(user=user, location_id=location_id)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)
    assert isinstance(result, Success)
    return [
        VacantShiftOut(
            id=row.id,
            template_name=row.template_name,
            template_id=row.template_id,
            role_target=row.role_target,
            location_id=row.location_id,
            location_name=row.location_name,
            scheduled_start=row.scheduled_start,
            scheduled_end=row.scheduled_end,
            station_label=row.station_label,
            slot_index=row.slot_index,
        )
        for row in result.value
    ]


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


@router.post("/{shift_id}/claim", response_model=CurrentShiftResponse)
async def claim_shift(
    shift_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    body: Annotated[StartShiftIn | None, Body()] = None,
) -> CurrentShiftResponse:
    geo = body or StartShiftIn()
    use_case = ClaimShiftUseCase(session=session)
    result = await use_case.execute(
        shift_id=shift_id,
        user=user,
        client_latitude=geo.client_latitude,
        client_longitude=geo.client_longitude,
        client_accuracy_m=geo.client_accuracy_m,
    )
    if isinstance(result, Failure):
        if result.error.code == "insufficient_role":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
        raise_for_domain_failure(result)
    assert isinstance(result, Success)

    read_use_case = ListMyShiftUseCase(session=session)
    read_result = await read_use_case.execute(user=user)
    if isinstance(read_result, Failure):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=read_result.error.code)
    assert isinstance(read_result, Success)
    return CurrentShiftResponse.model_validate(read_result.value, from_attributes=True)


@router.post("/{shift_id}/start", response_model=CurrentShiftResponse)
async def start_shift(
    shift_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    body: Annotated[StartShiftIn | None, Body()] = None,
) -> CurrentShiftResponse:
    geo = body or StartShiftIn()
    use_case = StartShiftUseCase(session=session)
    result = await use_case.execute(
        shift_id=shift_id,
        user=user,
        client_latitude=geo.client_latitude,
        client_longitude=geo.client_longitude,
        client_accuracy_m=geo.client_accuracy_m,
    )
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
        min_mean_luminance_255=settings.antifake_min_mean_luminance_255,
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
        raise_for_domain_failure(result)
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
    body: CloseShiftIn = Body(default_factory=CloseShiftIn),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> CloseShiftResponse:
    use_case = CloseShiftUseCase(session=session)
    result = await use_case.execute(
        shift_id=shift_id,
        user=user,
        confirm_violations=body.confirm_violations,
        delay_reason=body.delay_reason,
    )
    if isinstance(result, Failure):
        if result.error.code == "delay_reason_too_long":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error.code,
            )
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


class MyScheduledShiftOut(BaseModel):
    id: UUID
    template_name: str
    location_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int


@router.get("/my-scheduled", response_model=list[MyScheduledShiftOut])
async def my_scheduled_shifts(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[MyScheduledShiftOut]:
    use_case = ListMyScheduledShiftsUseCase(session=session)
    result = await use_case.execute(user=user)
    assert isinstance(result, Success)
    return [
        MyScheduledShiftOut(
            id=row.id,
            template_name=row.template_name,
            location_name=row.location_name,
            scheduled_start=row.scheduled_start.isoformat(),
            scheduled_end=row.scheduled_end.isoformat(),
            station_label=row.station_label,
            slot_index=row.slot_index,
        )
        for row in result.value
    ]


class SwapLinkPreviewOut(BaseModel):
    shift_id: UUID
    template_name: str
    location_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int
    proposer_user_id: UUID
    proposer_full_name: str


@router.get(
    "/{shift_id}/swap-link-preview",
    response_model=SwapLinkPreviewOut,
    summary="Context for a swap invite deep link (proposer shift)",
)
async def swap_link_preview(
    shift_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> SwapLinkPreviewOut:
    use_case = SwapLinkPreviewUseCase(session=session)
    result = await use_case.execute(user=user, proposer_shift_id=shift_id)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)
    assert isinstance(result, Success)
    p = result.value
    return SwapLinkPreviewOut(
        shift_id=p.shift_id,
        template_name=p.template_name,
        location_name=p.location_name,
        scheduled_start=p.scheduled_start,
        scheduled_end=p.scheduled_end,
        station_label=p.station_label,
        slot_index=p.slot_index,
        proposer_user_id=p.proposer_user_id,
        proposer_full_name=p.proposer_full_name,
    )


class SwapRequestCreateIn(BaseModel):
    proposer_shift_id: UUID
    counterparty_shift_id: UUID
    message: str | None = None


class SwapRequestOut(BaseModel):
    id: UUID
    status: str
    message: str | None
    created_at: str
    resolved_at: str | None
    proposer_user_id: UUID
    proposer_name: str
    counterparty_user_id: UUID
    counterparty_name: str
    proposer_shift_id: UUID
    counterparty_shift_id: UUID


@router.post("/swap-requests", response_model=dict[str, UUID])
async def create_swap_request(
    body: SwapRequestCreateIn,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, UUID]:
    use_case = CreateSwapShiftRequestUseCase(session=session)
    result = await use_case.execute(
        user=user,
        proposer_shift_id=body.proposer_shift_id,
        counterparty_shift_id=body.counterparty_shift_id,
        message=body.message,
    )
    if isinstance(result, Failure):
        raise_for_domain_failure(result)
    assert isinstance(result, Success)
    return {"id": result.value}


@router.get("/swap-requests", response_model=list[SwapRequestOut])
async def list_swap_requests(
    direction: Annotated[Literal["in", "out"], Query()],
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[SwapRequestOut]:
    use_case = ListSwapShiftRequestsUseCase(session=session)
    result = await use_case.execute(user=user, direction=direction)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)
    assert isinstance(result, Success)
    return [
        SwapRequestOut(
            id=r.id,
            status=r.status,
            message=r.message,
            created_at=r.created_at.isoformat(),
            resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
            proposer_user_id=r.proposer_user_id,
            proposer_name=r.proposer_name,
            counterparty_user_id=r.counterparty_user_id,
            counterparty_name=r.counterparty_name,
            proposer_shift_id=r.proposer_shift_id,
            counterparty_shift_id=r.counterparty_shift_id,
        )
        for r in result.value
    ]


@router.post("/swap-requests/{request_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_swap_request(
    request_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    use_case = AcceptSwapShiftRequestUseCase(session=session)
    result = await use_case.execute(user=user, request_id=request_id)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)


@router.post("/swap-requests/{request_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_swap_request(
    request_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    use_case = DeclineSwapShiftRequestUseCase(session=session)
    result = await use_case.execute(user=user, request_id=request_id)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)


@router.delete("/swap-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_swap_request(
    request_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    use_case = CancelSwapShiftRequestUseCase(session=session)
    result = await use_case.execute(user=user, request_id=request_id)
    if isinstance(result, Failure):
        raise_for_domain_failure(result)
