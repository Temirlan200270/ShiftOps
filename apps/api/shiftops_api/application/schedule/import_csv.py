"""CSV schedule import.

Why a CSV importer instead of a "create shift" UI
-------------------------------------------------
Pilot HoReCa locations already maintain weekly rosters in Excel/Google
Sheets. Forcing the admin (Anna) to retype every shift into a phone
form is friction that kills adoption — the import sheet is the single
biggest backend lever to keep the pilot rolling.

Format (UTF-8, comma- or semicolon-separated, header row required)::

    date,time_start,time_end,location,template,operator
    2026-04-29,09:00,17:00,Bar #1,Morning bar,@ivanov
    2026-04-30,18:00,02:00,Bar #1,Evening bar,@petrov

Resolution rules:

- ``date`` ISO-8601 (``YYYY-MM-DD``); local-clock at the location.
- ``time_start``/``time_end`` ``HH:MM``. End < start means "next day" and
  is converted to a date+1 boundary so a 22:00→06:00 shift works.
- ``location`` matches by *exact case-insensitive name*. The admin
  manages locations elsewhere; we never auto-create one because that's
  how typos become silent ghost rows.
- ``template`` matches by exact case-insensitive name within the org.
- ``operator`` matches by Telegram username (``@handle`` or just
  ``handle``) OR by the ``telegram_accounts`` row's ``tg_user_id`` if
  the cell is a numeric id.

Validation strategy: we do TWO passes over the same CSV. The first
("dry run") returns per-row errors so the UI can show "row 7 failed
because location not found"; the second performs the inserts.

A single bad row never aborts the whole import. We collect errors,
return them, and skip the row. The admin re-uploads the corrected file
later.

Concurrency / idempotency
-------------------------
Two operators can clearly work the same shift slot at different
locations, so we do NOT enforce uniqueness across (location, scheduled_start).
However we DO refuse to create a second shift for the same operator on
the same day at the same time — accidental duplicates are otherwise
the most common pilot bug.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.timezone import require_iana_timezone
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import (
    Location,
    Shift,
    TaskInstance,
    TelegramAccount,
    Template,
    TemplateTask,
    User,
)
from shiftops_api.infra.metrics import CSV_IMPORT_ROWS_TOTAL

MAX_ROWS = 500
HEADER_REQUIRED = {"date", "time_start", "time_end", "location", "template", "operator"}


@dataclass(frozen=True, slots=True)
class ImportRowError:
    line_no: int
    code: str
    message: str
    columns: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportRowResult:
    line_no: int
    date: str
    time_start: str
    time_end: str
    location: str
    template: str
    operator: str
    shift_id: uuid.UUID | None = None  # None on dry-run or on error


@dataclass(frozen=True, slots=True)
class ImportReport:
    total_rows: int
    created: list[ImportRowResult]
    skipped: list[ImportRowResult]  # validated but not created (dry_run)
    errors: list[ImportRowError]
    dry_run: bool


@dataclass
class _ParsedRow:
    line_no: int
    raw: dict[str, str]
    date: date | None = None
    time_start: time | None = None
    time_end: time | None = None
    location_id: uuid.UUID | None = None
    location_tz: str | None = None
    template_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


class ImportScheduleCsvUseCase:
    """Bulk-create scheduled shifts from a CSV upload.

    Caller responsibilities:
    - feed UTF-8 ``bytes`` (the HTTP layer reads ``UploadFile.read()``);
    - decide ``dry_run`` based on a query parameter / form field.
    """

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        file_bytes: bytes,
        dry_run: bool,
    ) -> Result[ImportReport, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return Failure(DomainError("invalid_encoding", message="UTF-8 required"))

        # Detect delimiter once. Sniff fails on tiny inputs, so default to ','.
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if reader.fieldnames is None:
            return Failure(DomainError("missing_header"))

        normalized = {(name or "").strip().lower(): name for name in reader.fieldnames}
        missing = HEADER_REQUIRED - set(normalized.keys())
        if missing:
            return Failure(
                DomainError(
                    "missing_columns",
                    message=", ".join(sorted(missing)),
                )
            )

        # Header row counts as line 1 in user-facing messages.
        rows: list[_ParsedRow] = []
        for offset, raw in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                return Failure(
                    DomainError(
                        "too_many_rows",
                        message=f"limit is {MAX_ROWS} rows per upload",
                    )
                )
            normalized_raw = {
                key: (raw.get(actual, "") or "").strip() for key, actual in normalized.items()
            }
            if not any(normalized_raw.values()):
                continue  # blank line — ignore silently
            rows.append(_ParsedRow(line_no=offset, raw=normalized_raw))

        if not rows:
            return Success(
                ImportReport(
                    total_rows=0,
                    created=[],
                    skipped=[],
                    errors=[],
                    dry_run=dry_run,
                )
            )

        errors: list[ImportRowError] = []

        # Resolve string references in batches — one round-trip per resolver.
        location_index = await self._index_locations(user.organization_id)
        template_index = await self._index_templates(user.organization_id)
        operator_index = await self._index_operators(user.organization_id)

        for row in rows:
            err = _parse_dates_times(row)
            if err is not None:
                errors.append(err)
                continue

            loc = location_index.get(row.raw["location"].lower())
            if loc is None:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="unknown_location",
                        message=f"location '{row.raw['location']}' not found",
                        columns={"location": row.raw["location"]},
                    )
                )
                continue
            row.location_id, raw_tz = loc
            try:
                row.location_tz = require_iana_timezone(raw_tz or "UTC")
            except ValueError as exc:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="invalid_location_timezone",
                        message=str(exc),
                        columns={"location": row.raw["location"]},
                    )
                )
                continue

            tpl = template_index.get(row.raw["template"].lower())
            if tpl is None:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="unknown_template",
                        message=f"template '{row.raw['template']}' not found",
                        columns={"template": row.raw["template"]},
                    )
                )
                continue
            row.template_id = tpl

            op_user = _resolve_operator(operator_index, row.raw["operator"])
            if op_user is None:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="unknown_operator",
                        message=f"operator '{row.raw['operator']}' not found",
                        columns={"operator": row.raw["operator"]},
                    )
                )
                continue
            row.operator_id = op_user

            assert row.date and row.time_start and row.time_end
            try:
                tzinfo = ZoneInfo(row.location_tz or "UTC")
            except ZoneInfoNotFoundError:
                tzinfo = UTC

            start_local = datetime.combine(row.date, row.time_start, tzinfo=tzinfo)
            end_date = row.date if row.time_end > row.time_start else row.date + timedelta(days=1)
            end_local = datetime.combine(end_date, row.time_end, tzinfo=tzinfo)

            row.scheduled_start = start_local.astimezone(UTC)
            row.scheduled_end = end_local.astimezone(UTC)

            if row.scheduled_start >= row.scheduled_end:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="empty_window",
                        message="time_end must be after time_start",
                    )
                )
                continue

            if row.scheduled_start < datetime.now(tz=UTC) - timedelta(hours=1):
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="past_window",
                        message="scheduled_start is in the past",
                    )
                )
                continue

        # Ahead-of-create duplicate check: same (operator, scheduled_start)
        # already exists. We treat this as an error so the admin sees
        # exactly which row was redundant and isn't surprised by silently
        # ignored inserts.
        valid_rows = [r for r in rows if r.operator_id is not None]
        existing = await self._existing_starts(
            [(r.operator_id, r.scheduled_start) for r in valid_rows if r.scheduled_start],
        )
        for row in valid_rows:
            if row.scheduled_start and (row.operator_id, row.scheduled_start) in existing:
                errors.append(
                    ImportRowError(
                        line_no=row.line_no,
                        code="duplicate_shift",
                        message="operator already has a shift at this start",
                    )
                )

        ok_rows = _drop_errored(rows, errors)
        created: list[ImportRowResult] = []
        skipped: list[ImportRowResult] = []

        if dry_run:
            for row in ok_rows:
                skipped.append(_to_row_result(row))
        else:
            # Pre-load template tasks once per template so we don't re-query
            # for every row that uses the same template.
            template_ids = {row.template_id for row in ok_rows if row.template_id}
            tt_by_template = await self._load_template_tasks(template_ids)

            for row in ok_rows:
                shift = Shift(
                    organization_id=user.organization_id,
                    location_id=row.location_id,
                    template_id=row.template_id,
                    operator_user_id=row.operator_id,
                    scheduled_start=row.scheduled_start,
                    scheduled_end=row.scheduled_end,
                    status=ShiftStatus.SCHEDULED.value,
                )
                self._session.add(shift)
                await self._session.flush()  # need shift.id

                for tt in tt_by_template.get(row.template_id, []):
                    self._session.add(
                        TaskInstance(
                            shift_id=shift.id,
                            template_task_id=tt.id,
                            status=TaskStatus.PENDING.value,
                        )
                    )

                created.append(_to_row_result(row, shift_id=shift.id))

            await write_audit(
                session=self._session,
                organization_id=user.organization_id,
                actor_user_id=user.id,
                event_type="schedule.imported",
                payload={
                    "rows_total": len(rows),
                    "rows_created": len(created),
                    "rows_errored": len(errors),
                },
            )
            await self._session.commit()

        # Per-row metrics give us a clean view of CSV health over time.
        # `dry_run` is its own bucket so dashboards can split "validation
        # work" from "real imports" without label introspection.
        if dry_run:
            CSV_IMPORT_ROWS_TOTAL.labels(outcome="dry_run").inc(len(skipped))
        else:
            CSV_IMPORT_ROWS_TOTAL.labels(outcome="created").inc(len(created))
        if errors:
            CSV_IMPORT_ROWS_TOTAL.labels(outcome="error").inc(len(errors))

        return Success(
            ImportReport(
                total_rows=len(rows),
                created=created,
                skipped=skipped,
                errors=errors,
                dry_run=dry_run,
            )
        )

    async def _index_locations(self, org_id: uuid.UUID) -> dict[str, tuple[uuid.UUID, str]]:
        rows = (
            await self._session.execute(
                select(Location.id, Location.name, Location.timezone).where(
                    Location.organization_id == org_id
                )
            )
        ).all()
        return {name.lower(): (row_id, tz) for row_id, name, tz in rows}

    async def _index_templates(self, org_id: uuid.UUID) -> dict[str, uuid.UUID]:
        rows = (
            await self._session.execute(
                select(Template.id, Template.name).where(Template.organization_id == org_id)
            )
        ).all()
        return {name.lower(): row_id for row_id, name in rows}

    async def _index_operators(self, org_id: uuid.UUID) -> _OperatorIndex:
        # Telegram username currently lives on the telegram_accounts row;
        # the User model itself has no @handle column. We index by both
        # the tg_user_id (numeric) and the username so the CSV admin can
        # use either spelling.
        rows = (
            await self._session.execute(
                select(
                    User.id,
                    User.full_name,
                    TelegramAccount.tg_user_id,
                    TelegramAccount.tg_username,
                )
                .join(TelegramAccount, TelegramAccount.user_id == User.id, isouter=True)
                .where(User.organization_id == org_id)
                .where(User.is_active.is_(True))
            )
        ).all()
        by_username: dict[str, uuid.UUID] = {}
        by_tg_id: dict[int, uuid.UUID] = {}
        by_full_name: dict[str, uuid.UUID] = {}
        for user_id, full_name, tg_user_id, username in rows:
            by_full_name.setdefault(full_name.lower(), user_id)
            if username:
                by_username[username.lstrip("@").lower()] = user_id
            if tg_user_id:
                by_tg_id[int(tg_user_id)] = user_id
        return _OperatorIndex(by_username=by_username, by_tg_id=by_tg_id, by_full_name=by_full_name)

    async def _existing_starts(
        self,
        candidates: list[tuple[uuid.UUID, datetime]],
    ) -> set[tuple[uuid.UUID, datetime]]:
        if not candidates:
            return set()
        operator_ids = list({op for op, _ in candidates})
        starts = list({s for _, s in candidates})
        rows = (
            await self._session.execute(
                select(Shift.operator_user_id, Shift.scheduled_start)
                .where(Shift.operator_user_id.in_(operator_ids))
                .where(Shift.scheduled_start.in_(starts))
                .where(
                    Shift.status.in_(
                        [
                            ShiftStatus.SCHEDULED,
                            ShiftStatus.ACTIVE,
                            ShiftStatus.CLOSED_CLEAN,
                            ShiftStatus.CLOSED_WITH_VIOLATIONS,
                        ]
                    )
                )
            )
        ).all()
        return {(op, st) for op, st in rows}

    async def _load_template_tasks(
        self, template_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, list[TemplateTask]]:
        if not template_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    select(TemplateTask)
                    .where(TemplateTask.template_id.in_(template_ids))
                    .order_by(TemplateTask.template_id, TemplateTask.order_index)
                )
            )
            .scalars()
            .all()
        )
        out: dict[uuid.UUID, list[TemplateTask]] = {tid: [] for tid in template_ids}
        for tt in rows:
            out.setdefault(tt.template_id, []).append(tt)
        return out


@dataclass(frozen=True, slots=True)
class _OperatorIndex:
    by_username: dict[str, uuid.UUID]
    by_tg_id: dict[int, uuid.UUID]
    by_full_name: dict[str, uuid.UUID]


def _resolve_operator(idx: _OperatorIndex, raw: str) -> uuid.UUID | None:
    needle = raw.strip()
    if not needle:
        return None
    if needle.isdigit():
        return idx.by_tg_id.get(int(needle))
    handle = needle.lstrip("@").lower()
    return idx.by_username.get(handle) or idx.by_full_name.get(needle.lower())


def _parse_dates_times(row: _ParsedRow) -> ImportRowError | None:
    raw = row.raw
    try:
        row.date = date.fromisoformat(raw["date"])
    except (KeyError, ValueError):
        return ImportRowError(
            line_no=row.line_no,
            code="invalid_date",
            message="date must be YYYY-MM-DD",
            columns={"date": raw.get("date", "")},
        )
    try:
        row.time_start = _parse_time(raw["time_start"])
        row.time_end = _parse_time(raw["time_end"])
    except ValueError as exc:
        return ImportRowError(
            line_no=row.line_no,
            code="invalid_time",
            message=str(exc),
            columns={
                "time_start": raw.get("time_start", ""),
                "time_end": raw.get("time_end", ""),
            },
        )
    return None


def _parse_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"invalid time '{value}'")
    try:
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError(f"invalid time '{value}'") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        raise ValueError(f"out-of-range time '{value}'")
    return time(h, m, s)


def _drop_errored(rows: list[_ParsedRow], errors: list[ImportRowError]) -> list[_ParsedRow]:
    bad_lines = {e.line_no for e in errors}
    return [r for r in rows if r.line_no not in bad_lines]


def _to_row_result(row: _ParsedRow, *, shift_id: uuid.UUID | None = None) -> ImportRowResult:
    return ImportRowResult(
        line_no=row.line_no,
        date=row.raw.get("date", ""),
        time_start=row.raw.get("time_start", ""),
        time_end=row.raw.get("time_end", ""),
        location=row.raw.get("location", ""),
        template=row.raw.get("template", ""),
        operator=row.raw.get("operator", ""),
        shift_id=shift_id,
    )


__all__ = [
    "MAX_ROWS",
    "ImportReport",
    "ImportRowError",
    "ImportRowResult",
    "ImportScheduleCsvUseCase",
]


# Type-only re-exports for IDE follow-through. Reference here keeps the
# linter happy without polluting the runtime namespace.
_ = Any
