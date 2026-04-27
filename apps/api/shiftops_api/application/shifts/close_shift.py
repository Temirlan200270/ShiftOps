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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import Criticality, ShiftStatus, TaskStatus, UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.domain.score import (
    ShiftScoreBreakdown,
    ShiftScoreInputs,
    compute_score,
)
from shiftops_api.infra.db.models import Attachment, Shift, TaskInstance, TemplateTask


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
    ) -> Result[ClosedShift, DomainError]:
        shift = (
            await self._session.execute(select(Shift).where(Shift.id == shift_id))
        ).scalar_one_or_none()
        if shift is None:
            return Failure(DomainError("shift_not_found"))

        if user.role == UserRole.OPERATOR and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.ACTIVE:
            return Failure(DomainError("shift_not_active"))

        rows = (
            await self._session.execute(
                select(TaskInstance, TemplateTask).join(
                    TemplateTask, TemplateTask.id == TaskInstance.template_task_id
                ).where(TaskInstance.shift_id == shift_id)
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
            },
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import dispatch_shift_closed

        await dispatch_shift_closed(shift_id=shift.id, final_status=final_status.value)

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
