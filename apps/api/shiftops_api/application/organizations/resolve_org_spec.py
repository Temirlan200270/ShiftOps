"""Resolve Telegram super-admin org arguments (UUID or exact name) to id."""

from __future__ import annotations

import html
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.db.models import Organization
from shiftops_api.infra.db.rls import enter_privileged_rls_mode


def _parse_uuid_token(token: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(token.strip())
    except ValueError:
        return None


async def resolve_org_spec_to_uuid(
    session: AsyncSession,
    org_spec: str,
    *,
    rls_reason: str = "telegram_bot_resolve_org_spec",
) -> tuple[uuid.UUID | None, str | None]:
    """Return ``(organization_id, None)`` or ``(None, html_error_message)``."""

    await enter_privileged_rls_mode(session, reason=rls_reason)
    token = org_spec.strip().strip("'\"")
    if not token:
        return None, "Укажите <b>название</b> организации или её <b>UUID</b>."
    uid = _parse_uuid_token(token)
    if uid is not None:
        org = await session.get(Organization, uid)
        if org is None:
            return None, "Организация с таким UUID не найдена."
        return uid, None

    rows = (
        await session.execute(
            select(Organization.id, Organization.name).where(
                func.lower(Organization.name) == func.lower(token)
            )
        )
    ).all()
    if len(rows) == 1:
        return rows[0][0], None
    if len(rows) > 1:
        lines = "\n".join(f"• <code>{r[0]}</code> — {html.escape(r[1])}" for r in rows)
        return (
            None,
            "Несколько организаций с таким именем — укажите UUID:\n" + lines,
        )

    return (
        None,
        f"Организация «<b>{html.escape(token)}</b>» не найдена. "
        "Проверьте название (как в ответе <code>/create_org</code>) или вставьте UUID.",
    )
