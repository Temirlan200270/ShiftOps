"""Audit trail endpoints (read-only, owner/admin).

This is intentionally minimal: a lightweight UI can show recent changes
without building a full analytics product.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.db.models import AuditEvent, Location, Shift, Template, User

router = APIRouter()

_view_audit = require_role(UserRole.ADMIN, UserRole.OWNER)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 30


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime = Field(description="UTC timestamp")
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    event_type: str = Field(description="Stable machine code for UI (icons, accents)")
    accent: str = Field(
        description="UI hint: neutral | positive | warning | danger | info",
    )
    message: str


class AuditPageOut(BaseModel):
    items: list[AuditEventOut]
    next_cursor: datetime | None = Field(
        default=None, description="Pass as ?cursor= on the next page request"
    )


@router.get(
    "/events",
    response_model=AuditPageOut,
    summary="Recent audit events for the organization (admin/owner)",
)
async def list_audit_events(
    cursor: datetime | None = Query(
        default=None, description="ISO timestamp from next_cursor of a previous response"
    ),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    event_type: str | None = Query(default=None, description="Optional exact event_type filter"),
    user: CurrentUser = Depends(_view_audit),
    session: AsyncSession = Depends(get_session),
) -> AuditPageOut:
    stmt = (
        select(
            AuditEvent.id,
            AuditEvent.created_at,
            AuditEvent.event_type,
            AuditEvent.actor_user_id,
            User.full_name,
            AuditEvent.payload,
        )
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.organization_id == user.organization_id)
    )
    if cursor is not None:
        # Keyset pagination (DESC): fetch items strictly older than cursor.
        stmt = stmt.where(AuditEvent.created_at < cursor)
    if event_type is not None:
        stmt = stmt.where(AuditEvent.event_type == event_type)

    rows = (
        await session.execute(stmt.order_by(desc(AuditEvent.created_at)).limit(limit + 1))
    ).all()

    items_raw = rows[:limit]
    next_cursor = items_raw[-1][1] if len(rows) > limit and items_raw else None

    payloads: list[dict[str, Any]] = [row[5] or {} for row in items_raw]
    shift_ids: set[uuid.UUID] = set()
    template_ids: set[uuid.UUID] = set()
    location_ids: set[uuid.UUID] = set()
    member_user_ids: set[uuid.UUID] = set()

    def _maybe_uuid(v: object) -> uuid.UUID | None:
        if not isinstance(v, str):
            return None
        try:
            return uuid.UUID(v)
        except Exception:
            return None

    for p in payloads:
        sid = _maybe_uuid(p.get("shift_id"))
        if sid is not None:
            shift_ids.add(sid)
        tid = _maybe_uuid(p.get("template_id"))
        if tid is not None:
            template_ids.add(tid)
        lid = _maybe_uuid(p.get("location_id"))
        if lid is not None:
            location_ids.add(lid)
        mid = _maybe_uuid(p.get("target_user_id"))
        if mid is not None:
            member_user_ids.add(mid)

    # Batch-resolve names so we don't do N+1 queries.
    shift_lookup: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    if shift_ids:
        shift_rows = (
            await session.execute(
                select(Shift.id, Template.name, Location.name)
                .join(Template, Template.id == Shift.template_id)
                .join(Location, Location.id == Shift.location_id)
                .where(Shift.id.in_(shift_ids))
            )
        ).all()
        shift_lookup = {r[0]: (r[1], r[2]) for r in shift_rows}

    template_lookup: dict[uuid.UUID, str] = {}
    if template_ids:
        tpl_rows = (
            await session.execute(
                select(Template.id, Template.name).where(Template.id.in_(template_ids))
            )
        ).all()
        template_lookup = {r[0]: r[1] for r in tpl_rows}

    location_lookup: dict[uuid.UUID, str] = {}
    if location_ids:
        loc_rows = (
            await session.execute(
                select(Location.id, Location.name).where(Location.id.in_(location_ids))
            )
        ).all()
        location_lookup = {r[0]: r[1] for r in loc_rows}

    member_name_lookup: dict[uuid.UUID, str] = {}
    if member_user_ids:
        mu_rows = (
            await session.execute(
                select(User.id, User.full_name).where(User.id.in_(member_user_ids))
            )
        ).all()
        member_name_lookup = {r[0]: r[1] for r in mu_rows}

    def _audit_accent(event_type: str, payload: dict[str, Any]) -> str:
        """UI accent for border/icon; keep in sync with web ``auditAccentClass``."""

        if event_type == "shift.started":
            if payload.get("suspicious_location") is True:
                return "warning"
            return "positive"
        if event_type == "shift.closed":
            if payload.get("final_status") == "closed_with_violations":
                return "warning"
            return "positive"
        if event_type == "template.deleted":
            return "danger"
        if event_type == "waiver.requested":
            return "warning"
        if event_type == "waiver.reject":
            return "danger"
        if event_type == "waiver.approve":
            return "positive"
        if event_type == "schedule.imported":
            return "info"
        if event_type == "task.completed":
            if payload.get("suspicious") is True:
                return "warning"
            return "neutral"
        if event_type in ("template.created", "template.updated"):
            return "neutral"
        if event_type == "member.updated":
            return "info"
        return "neutral"

    def _human_message(
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        if event_type == "shift.started":
            sid = _maybe_uuid(payload.get("shift_id"))
            tpl, loc = shift_lookup.get(sid, (None, None)) if sid else (None, None)
            base = ""
            if tpl and loc:
                base = f"Начал смену «{tpl}» на локации «{loc}»."
            elif loc_id := _maybe_uuid(payload.get("location_id")):
                loc_name = location_lookup.get(loc_id)
                if loc_name:
                    base = f"Начал смену на локации «{loc_name}»."
            if not base:
                base = "Начал смену."
            if payload.get("suspicious_location") is True:
                return base + " Метка: подозрительная геолокация (далеко от точки)."
            return base

        if event_type == "shift.closed":
            sid = _maybe_uuid(payload.get("shift_id"))
            tpl, loc = shift_lookup.get(sid, (None, None)) if sid else (None, None)
            status = payload.get("final_status")
            missed_required = payload.get("required_missed")
            missed_count = len(missed_required) if isinstance(missed_required, list) else 0
            base = (
                "Закрыл смену"
                + (f" «{tpl}»" if tpl else "")
                + (f" на локации «{loc}»" if loc else "")
            )
            if status == "closed_clean":
                return base + " без нарушений."
            if status == "closed_with_violations":
                return base + (f" с нарушениями (пропущено обязательных: {missed_count}).")
            return base + "."

        if event_type in ("template.created", "template.updated"):
            tid = _maybe_uuid(payload.get("template_id"))
            name = (template_lookup.get(tid) if tid else None) or payload.get("name")
            task_count = payload.get("task_count")
            verb = "создал" if event_type == "template.created" else "обновил"
            if isinstance(name, str) and name:
                tail = f" (задач: {task_count})." if isinstance(task_count, int) else "."
                return f"{verb.capitalize()} шаблон «{name}»{tail}"
            return f"{verb.capitalize()} шаблон."

        if event_type == "template.deleted":
            tid = _maybe_uuid(payload.get("template_id"))
            name = (template_lookup.get(tid) if tid else None) or payload.get("name")
            if isinstance(name, str) and name:
                return f"Удалил шаблон «{name}»."
            return "Удалил шаблон."

        if event_type == "schedule.imported":
            created = payload.get("rows_created")
            total = payload.get("rows_total")
            if isinstance(created, int) and isinstance(total, int):
                return f"Импортировал расписание: создано смен {created} из {total} строк."
            return "Импортировал расписание."

        if event_type == "waiver.requested":
            return "Запросил отступление (waiver) по задаче."

        if event_type == "waiver.approve":
            return "Одобрил отступление по задаче."

        if event_type == "waiver.reject":
            return "Отклонил отступление по задаче."

        if event_type == "task.completed":
            if payload.get("suspicious") is True:
                return "Отметил задачу выполненной (фото помечено как подозрительное)."
            return "Отметил задачу выполненной."

        if event_type == "member.updated":
            tid = _maybe_uuid(payload.get("target_user_id"))
            who = member_name_lookup.get(tid, "участник") if tid else "участник"
            bits: list[str] = []
            rp = payload.get("role")
            if isinstance(rp, dict):
                rf = rp.get("from")
                rt = rp.get("to")
                if isinstance(rf, str) and isinstance(rt, str):
                    bits.append(f"роль: {rf} → {rt}")
            jp = payload.get("job_title")
            if isinstance(jp, dict):
                jf = jp.get("from")
                jt = jp.get("to")
                if jf != jt:
                    def _jt_label(v: object) -> str:
                        if v is None or v == "":
                            return "—"
                        return str(v)

                    bits.append(f"должность: {_jt_label(jf)} → {_jt_label(jt)}")
            if bits:
                return f"Изменил участника «{who}»: " + "; ".join(bits) + "."
            return f"Обновил участника «{who}»."

        # Fallback: still avoid JSON and keep it human-ish.
        return f"Действие: {event_type}."

    items = [
        AuditEventOut(
            id=row[0],
            created_at=row[1].astimezone(UTC),
            actor_user_id=row[3],
            actor_name=row[4],
            event_type=row[2],
            accent=_audit_accent(row[2], row[5] or {}),
            message=_human_message(event_type=row[2], payload=(row[5] or {})),
        )
        for row in items_raw
    ]
    return AuditPageOut(items=items, next_cursor=next_cursor)

