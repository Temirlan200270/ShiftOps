"""Use-case: close the active shift.

Hard / soft block rules:

- HARD BLOCK: any `criticality=critical` task in `pending` / `waiver_pending`
  / `waiver_rejected` status -> Failure("critical_tasks_pending").
- SOFT WARNING: any `criticality=required` task not done -> caller must pass
  `confirm_violations=True`, and the shift closes as
  `closed_with_violations`.
- Otherwise -> `closed_clean`.

Score is computed by `domain.score.compute_score` and persisted on the row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import Criticality, ShiftStatus, TaskStatus, is_line_staff
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.domain.score import (
    ShiftScoreBreakdown,
    ShiftScoreInputs,
    compute_score,
)
from shiftops_api.infra.db.models import Attachment, Shift, TaskInstance, TemplateTask

_MAX_DELAY_REASON_LEN = 500


@dataclass(frozen=True, slots=True)
class ClosedShift:
    shift_id: uuid.UUID
    final_status: str
    score: Decimal
    breakdown: ShiftScoreBreakdown
    formula_version: int
    missed_required: int
    missed_critical: int


class CloseShiftUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        shift_id: uuid.UUID,
        user: CurrentUser,
        confirm_violations: bool,
        delay_reason: str | None = None,
    ) -> Result[ClosedShift, DomainError]:
        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one_or_none()
        if shift is None:
            return Failure(DomainError("shift_not_found"))

        if shift.operator_user_id is None:
            return Failure(DomainError("shift_not_claimed"))

        if is_line_staff(user.role) and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.ACTIVE:
            return Failure(DomainError("shift_not_active"))

        normalized_delay: str | None = None
        if delay_reason is not None:
            stripped = delay_reason.strip()
            if len(stripped) > _MAX_DELAY_REASON_LEN:
                return Failure(DomainError("delay_reason_too_long"))
            normalized_delay = stripped or None

        rows = (
            await self._session.execute(
                select(TaskInstance, TemplateTask)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .where(TaskInstance.shift_id == shift_id)
                .where(TaskInstance.status != TaskStatus.OBSOLETE.value)
            )
        ).all()
        if not rows:
            return Failure(DomainError("shift_has_no_tasks"))

        critical_total = 0
        critical_done_or_waived = 0
        required_total = 0
        required_done = 0
        total = 0
        done_or_waived = 0
        photo_total = 0

        critical_pending: list[uuid.UUID] = []
        required_missed: list[uuid.UUID] = []

        for task, tt in rows:
            total += 1
            criticality = Criticality(tt.criticality)
            status = TaskStatus(task.status)

            if criticality is Criticality.CRITICAL:
                critical_total += 1
                if status in (TaskStatus.DONE, TaskStatus.WAIVED):
                    critical_done_or_waived += 1
                else:
                    critical_pending.append(task.id)
            elif criticality is Criticality.REQUIRED:
                required_total += 1
                if status in (TaskStatus.DONE, TaskStatus.WAIVED):
                    required_done += 1
                else:
                    required_missed.append(task.id)

            if status in (TaskStatus.DONE, TaskStatus.WAIVED):
                done_or_waived += 1

            if tt.requires_photo and status == TaskStatus.DONE:
                photo_total += 1

        # HARD BLOCK
        if critical_pending:
            return Failure(
                DomainError(
                    "critical_tasks_pending",
                    details={"count": str(len(critical_pending))},
                )
            )

        if required_missed and not confirm_violations:
            return Failure(
                DomainError(
                    "required_tasks_missed_confirm_required",
                    details={"count": str(len(required_missed))},
                )
            )

        # Mark missed required as 'skipped' for audit clarity.
        if required_missed:
            await self._session.execute(
                TaskInstance.__table__.update()
                .where(TaskInstance.id.in_(required_missed))
                .values(status=TaskStatus.SKIPPED.value)
            )

        photo_unique = await self._count_unique_photos(shift_id)
        photo_total, suspicious_photos = await self._count_photos(shift_id)

        now = datetime.now(tz=UTC)
        score_result = compute_score(
            ShiftScoreInputs(
                total_tasks=total,
                done_or_waived=done_or_waived,
                critical_total=critical_total,
                critical_done_or_waived=critical_done_or_waived,
                photo_total=photo_total,
                photo_unique=photo_unique,
                scheduled_end=shift.scheduled_end,
                actual_end=now,
            )
        )

        final_status = (
            ShiftStatus.CLOSED_WITH_VIOLATIONS if required_missed else ShiftStatus.CLOSED_CLEAN
        )
        shift.status = final_status.value
        shift.actual_end = now
        shift.score = score_result.total
        # Persist *which* formula scored this shift. Future formula tweaks
        # never silently restate past scores — see docs/SCORE_FORMULA.md.
        shift.score_formula_version = score_result.formula_version
        shift.delay_reason = normalized_delay
        shift.handover_summary = _build_handover_summary(
            template_task_rows=rows,
            required_missed=required_missed,
            final_status=final_status.value,
            score=score_result.total,
            scheduled_end=shift.scheduled_end,
            actual_end=now,
            photo_total=photo_total,
            photo_unique=photo_unique,
            suspicious_photos=suspicious_photos,
        )

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="shift.closed",
            payload={
                "shift_id": str(shift.id),
                "final_status": final_status.value,
                "score": str(score_result.total),
                "score_breakdown": {
                    "completion": str(score_result.breakdown.completion),
                    "critical_compliance": str(score_result.breakdown.critical_compliance),
                    "timeliness": str(score_result.breakdown.timeliness),
                    "photo_quality": str(score_result.breakdown.photo_quality),
                },
                "formula_version": score_result.formula_version,
                "required_missed": [str(t) for t in required_missed],
                **({"delay_reason": normalized_delay} if normalized_delay else {}),
            },
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_shift_closed

        await dispatch_shift_closed(shift_id=shift.id, final_status=final_status.value)

        # Cleanup: drop obsolete tasks (they were hidden anyway). This keeps
        # the shift checklist tidy and reduces future FK conflicts when the
        # org edits templates again.
        await self._session.execute(
            TaskInstance.__table__.delete()
            .where(TaskInstance.shift_id == shift_id)
            .where(TaskInstance.status == TaskStatus.OBSOLETE.value)
        )
        await self._session.commit()

        return Success(
            ClosedShift(
                shift_id=shift.id,
                final_status=final_status.value,
                score=score_result.total,
                breakdown=score_result.breakdown,
                formula_version=score_result.formula_version,
                missed_required=len(required_missed),
                missed_critical=0,
            )
        )

    async def _count_unique_photos(self, shift_id: uuid.UUID) -> int:
        stmt = (
            select(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .where(TaskInstance.shift_id == shift_id)
        )
        attachments = (await self._session.execute(stmt)).scalars().all()
        return sum(1 for a in attachments if not a.suspicious)

    async def _count_photos(self, shift_id: uuid.UUID) -> tuple[int, int]:
        """Return ``(photo_total, suspicious_total)`` for the shift."""

        stmt = (
            select(
                func.count(Attachment.id).label("total"),
                func.count(Attachment.id)
                .filter(Attachment.suspicious.is_(True))
                .label("suspicious"),
            )
            .select_from(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .where(TaskInstance.shift_id == shift_id)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return 0, 0
        total, suspicious = row
        return int(total or 0), int(suspicious or 0)


def _build_handover_summary(
    *,
    template_task_rows: list[tuple[TaskInstance, TemplateTask]],
    required_missed: list[uuid.UUID],
    final_status: str,
    score: Decimal,
    scheduled_end: datetime,
    actual_end: datetime,
    photo_total: int,
    photo_unique: int,
    suspicious_photos: int,
) -> str:
    total = len(template_task_rows)
    done_or_waived = sum(
        1
        for ti, _tt in template_task_rows
        if TaskStatus(ti.status) in (TaskStatus.DONE, TaskStatus.WAIVED)
    )
    skipped = sum(
        1 for ti, _tt in template_task_rows if TaskStatus(ti.status) == TaskStatus.SKIPPED
    )
    waiver_pending = sum(
        1 for ti, _tt in template_task_rows if TaskStatus(ti.status) == TaskStatus.WAIVER_PENDING
    )
    # CloseShiftUseCase may leave WAIVER_REJECTED in the data set if it was pending,
    # but those count as "not done".
    waiver_rejected = sum(
        1 for ti, _tt in template_task_rows if TaskStatus(ti.status) == TaskStatus.WAIVER_REJECTED
    )

    late_min = max(0, int((actual_end - scheduled_end).total_seconds() // 60))
    status_emoji = "✅" if final_status == ShiftStatus.CLOSED_CLEAN.value else "🟠"

    missed_titles = [
        tt.title
        for ti, tt in template_task_rows
        if ti.id in required_missed  # NOTE: required_missed contains TaskInstance ids
    ]
    missed_preview = ""
    if missed_titles:
        clipped = missed_titles[:8]
        more = len(missed_titles) - len(clipped)
        lines = "\n".join(f"  - {t}" for t in clipped)
        tail = f"\n  …ещё {more}" if more > 0 else ""
        missed_preview = f"\n\nНе выполнено (required):\n{lines}{tail}"

    photos_line = f"{photo_unique}/{photo_total}" if photo_total else "0"
    suspicious_line = f", suspicious: {suspicious_photos}" if suspicious_photos else ""
    waiver_line = ""
    if waiver_pending or waiver_rejected:
        waiver_line = f"\nWaiver: pending {waiver_pending}, rejected {waiver_rejected}"

    late_line = f"\nОпоздание закрытия: {late_min} мин" if late_min > 0 else ""

    return (
        f"{status_emoji} Handover\n"
        f"Прогресс: {done_or_waived}/{total} (skipped {skipped})\n"
        f"Фото (unique/total): {photos_line}{suspicious_line}\n"
        f"Нарушения (required missed): {len(required_missed)}"
        f"{waiver_line}"
        f"{late_line}\n"
        f"Score: {score}%"
        f"{missed_preview}"
    )
