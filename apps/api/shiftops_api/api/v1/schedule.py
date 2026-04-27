"""Schedule HTTP endpoints — bulk import of shifts from CSV.

Why a separate module from ``shifts``: the import endpoint authenticates as
admin/owner and performs side effects across many rows, while ``shifts``
serves the per-operator runtime view. Mixing them couples two very
different lifecycles to one router file.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.schedule.import_csv import (
    MAX_ROWS,
    ImportScheduleCsvUseCase,
)
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_session

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


# 256 KB is well above what 500 rows × 6 columns of normal text take. We
# read the file fully into RAM (UploadFile.read()) so this caps memory.
_MAX_UPLOAD_BYTES = 256 * 1024


class ImportRowErrorOut(BaseModel):
    line_no: int
    code: str
    message: str
    columns: dict[str, str]


class ImportRowResultOut(BaseModel):
    line_no: int
    date: str
    time_start: str
    time_end: str
    location: str
    template: str
    operator: str
    shift_id: UUID | None


class ImportReportOut(BaseModel):
    total_rows: int
    created: list[ImportRowResultOut]
    skipped: list[ImportRowResultOut]
    errors: list[ImportRowErrorOut]
    dry_run: bool


@router.post(
    "/import",
    response_model=ImportReportOut,
    summary=f"Bulk-import up to {MAX_ROWS} shifts from a CSV upload",
)
async def import_schedule(
    file: UploadFile = File(..., description="CSV with header row"),
    dry_run: bool = Query(
        default=True,
        description="When true, validates and returns errors but doesn't insert.",
    ),
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> ImportReportOut:
    body = await file.read()
    if len(body) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file_too_large",
        )

    use_case = ImportScheduleCsvUseCase(session=session)
    result = await use_case.execute(user=user, file_bytes=body, dry_run=dry_run)
    if isinstance(result, Failure):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{result.error.code}:{result.error.message}",
        )
    assert isinstance(result, Success)
    report = result.value

    return ImportReportOut(
        total_rows=report.total_rows,
        created=[
            ImportRowResultOut(
                line_no=r.line_no,
                date=r.date,
                time_start=r.time_start,
                time_end=r.time_end,
                location=r.location,
                template=r.template,
                operator=r.operator,
                shift_id=r.shift_id,
            )
            for r in report.created
        ],
        skipped=[
            ImportRowResultOut(
                line_no=r.line_no,
                date=r.date,
                time_start=r.time_start,
                time_end=r.time_end,
                location=r.location,
                template=r.template,
                operator=r.operator,
                shift_id=None,
            )
            for r in report.skipped
        ],
        errors=[
            ImportRowErrorOut(
                line_no=e.line_no,
                code=e.code,
                message=e.message,
                columns=e.columns,
            )
            for e in report.errors
        ],
        dry_run=report.dry_run,
    )
