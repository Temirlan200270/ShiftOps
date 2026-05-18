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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from shiftops_api.infra.db.models import (
    Attachment,
    Location,
    Shift,
    TaskInstance,
    Template,
    TemplateTask,
    User,
)

_ROLE_LABELS: dict[str, str] = {
    "owner": "владелец",
    "admin": "администратор",
    "operator": "оператор",
    "bartender": "бармен",
}

_MAX_DELAY_REASON_LEN = 500
_MAX_VIOLATION_REASON_LEN = 500


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
        violation_reason: str | None = None,
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

        normalized_violation_reason: str | None = None
        if violation_reason is not None:
            stripped_v = violation_reason.strip()
            if len(stripped_v) > _MAX_VIOLATION_REASON_LEN:
                return Failure(DomainError("violation_reason_too_long"))
            normalized_violation_reason = stripped_v or None

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

        # Load context for the human-readable handover summary.
        tpl = (
            await self._session.execute(select(Template).where(Template.id == shift.template_id))
        ).scalar_one_or_none()
        loc = (
            await self._session.execute(select(Location).where(Location.id == shift.location_id))
        ).scalar_one_or_none()
        op = (
            (
                await self._session.execute(
                    select(User).where(User.id == shift.operator_user_id)
                )
            ).scalar_one_or_none()
            if shift.operator_user_id
            else None
        )
        operator_role_label = _ROLE_LABELS.get(str(op.role), str(op.role)) if op else None

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
        shift.violation_reason = normalized_violation_reason
        shift.handover_summary = _build_handover_summary(
            template_task_rows=rows,
            required_missed=required_missed,
            final_status=final_status.value,
            score=score_result.total,
            scheduled_start=shift.scheduled_start,
            scheduled_end=shift.scheduled_end,
            actual_start=shift.actual_start,
            actual_end=now,
            photo_total=photo_total,
            photo_unique=photo_unique,
            suspicious_photos=suspicious_photos,
            template_name=tpl.name if tpl else None,
            location_name=loc.name if loc else None,
            location_timezone=loc.timezone if loc else None,
            operator_name=f"{op.full_name} ({operator_role_label})" if op and operator_role_label else (op.full_name if op else None),
            violation_reason=normalized_violation_reason,
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
                **({"violation_reason": normalized_violation_reason} if normalized_violation_reason else {}),
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


def _fmt_duration(total_minutes: int) -> str:
    """Format minutes into human-readable duration: '4 дн. 2 ч. 58 мин.'"""
    if total_minutes <= 0:
        return "0 мин."
    days, rem = divmod(total_minutes, 60 * 24)
    hours, mins = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} дн.")
    if hours:
        parts.append(f"{hours} ч.")
    if mins or not parts:
        parts.append(f"{mins} мин.")
    return " ".join(parts)


def _fmt_local_dt(dt: datetime | None, tz_name: str | None) -> str:
    if dt is None:
        return "?"
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def _fmt_local_time(dt: datetime | None, tz_name: str | None) -> str:
    if dt is None:
        return "?"
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return dt.astimezone(tz).strftime("%H:%M")


def _build_handover_summary(
    *,
    template_task_rows: list[tuple[TaskInstance, TemplateTask]],
    required_missed: list[uuid.UUID],
    final_status: str,
    score: Decimal,
    scheduled_start: datetime,
    scheduled_end: datetime,
    actual_start: datetime | None,
    actual_end: datetime,
    photo_total: int,
    photo_unique: int,
    suspicious_photos: int,
    template_name: str | None = None,
    location_name: str | None = None,
    location_timezone: str | None = None,
    operator_name: str | None = None,
    violation_reason: str | None = None,
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
    waiver_rejected = sum(
        1 for ti, _tt in template_task_rows if TaskStatus(ti.status) == TaskStatus.WAIVER_REJECTED
    )

    is_clean = final_status == ShiftStatus.CLOSED_CLEAN.value
    status_line = "✅ Смена закрыта — без нарушений" if is_clean else "🟠 Смена закрыта — с нарушениями"

    tz = location_timezone

    lines: list[str] = [status_line]

    # Context block
    if location_name or template_name:
        ctx_parts = []
        if location_name:
            ctx_parts.append(location_name)
        if template_name:
            ctx_parts.append(template_name)
        lines.append("📍 " + " · ".join(ctx_parts))
    if operator_name:
        lines.append(f"👤 {operator_name}")

    lines.append("")

    # Timeline
    open_time = _fmt_local_time(actual_start, tz)
    close_time = _fmt_local_dt(actual_end, tz)
    sched_open = _fmt_local_time(scheduled_start, tz)
    sched_close = _fmt_local_time(scheduled_end, tz)
    lines.append(f"🕐 Расписание: {sched_open} → {sched_close}")
    lines.append(f"   Факт:       {open_time} → {close_time}")

    # Late close
    late_min = max(0, int((actual_end - scheduled_end).total_seconds() // 60))
    if late_min > 15:
        lines.append(f"⏰ Опоздание закрытия: +{_fmt_duration(late_min)}")

    lines.append("")

    # Tasks
    tasks_line = f"📋 Задачи: {done_or_waived}/{total} выполнено"
    if skipped:
        tasks_line += f"  (пропущено {skipped})"
    lines.append(tasks_line)

    # Photos
    if photo_total:
        photos_line = f"📸 Фото: {photo_unique} уник. / {photo_total} всего"
        if suspicious_photos:
            photos_line += f"  ⚠️ {suspicious_photos} подозрит."
        lines.append(photos_line)
    else:
        lines.append("📸 Фото: нет")

    # Score
    lines.append(f"⭐ Оценка: {score:.1f}%")

    # Violations
    if required_missed or waiver_pending or waiver_rejected:
        lines.append("")
        if required_missed:
            missed_titles = [
                tt.title
                for ti, tt in template_task_rows
                if ti.id in required_missed
            ]
            clipped = missed_titles[:8]
            more = len(missed_titles) - len(clipped)
            lines.append(f"❗ Обязательные задачи не выполнены ({len(required_missed)} шт.):")
            for t in clipped:
                lines.append(f"  — {t}")
            if more:
                lines.append(f"  … ещё {more}")
        if waiver_pending:
            lines.append(f"⏳ Ждут решения у администратора: {waiver_pending}")
        if waiver_rejected:
            lines.append(f"❌ Администратор не разрешил пропустить: {waiver_rejected}")

    if violation_reason:
        lines.append(f"\n📝 Причина нарушений: {violation_reason}")

    return "\n".join(lines)
