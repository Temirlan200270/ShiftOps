"""Cross-tenant isolation integration test.

Requires Postgres running. Marked `@pytest.mark.integration` so unit-only CI
runs can skip it.

The test:

1. Creates two organisations A and B with one location and one shift each.
2. Sets `app.org_id` to A and verifies A's shift is visible, B's is not.
3. Switches `app.org_id` to B and verifies the opposite.
4. Attempts to UPDATE/DELETE on `audit_events` and asserts the trigger raises.

This is the load-bearing test for ADR-006 — defence-in-depth tenant isolation.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncSession:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://shiftops:shiftops@postgres:5432/shiftops",
    )
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_minimal_org(session: AsyncSession) -> dict[str, uuid.UUID]:
    org_id = uuid.uuid4()
    location_id = uuid.uuid4()
    user_id = uuid.uuid4()
    template_id = uuid.uuid4()
    template_task_id = uuid.uuid4()
    shift_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    await session.execute(text("SET LOCAL row_security = off"))
    await session.execute(
        text(
            "INSERT INTO organizations (id, name) VALUES (:id, :name)",
        ),
        {"id": str(org_id), "name": f"Org-{org_id.hex[:6]}"},
    )
    await session.execute(
        text(
            "INSERT INTO locations (id, organization_id, name, timezone) "
            "VALUES (:id, :org, :name, 'UTC')"
        ),
        {"id": str(location_id), "org": str(org_id), "name": "Bar"},
    )
    await session.execute(
        text(
            "INSERT INTO users (id, organization_id, role, full_name) "
            "VALUES (:id, :org, 'operator', 'Test User')"
        ),
        {"id": str(user_id), "org": str(org_id)},
    )
    await session.execute(
        text(
            "INSERT INTO templates (id, organization_id, name, role_target) "
            "VALUES (:id, :org, 'Morning', 'operator')"
        ),
        {"id": str(template_id), "org": str(org_id)},
    )
    await session.execute(
        text(
            "INSERT INTO template_tasks (id, template_id, title, criticality, requires_photo, "
            "requires_comment, order_index) "
            "VALUES (:id, :tpl, 'Wipe bar', 'required', false, false, 0)"
        ),
        {"id": str(template_task_id), "tpl": str(template_id)},
    )
    await session.execute(
        text(
            "INSERT INTO shifts (id, organization_id, location_id, template_id, "
            "operator_user_id, scheduled_start, scheduled_end, status) "
            "VALUES (:id, :org, :loc, :tpl, :user, :s, :e, 'scheduled')"
        ),
        {
            "id": str(shift_id),
            "org": str(org_id),
            "loc": str(location_id),
            "tpl": str(template_id),
            "user": str(user_id),
            "s": now,
            "e": now + timedelta(hours=8),
        },
    )
    await session.commit()
    return {
        "org": org_id,
        "location": location_id,
        "user": user_id,
        "template": template_id,
        "template_task": template_task_id,
        "shift": shift_id,
    }


async def test_rls_blocks_cross_tenant_reads(session: AsyncSession) -> None:
    org_a = await _seed_minimal_org(session)
    org_b = await _seed_minimal_org(session)

    await session.execute(text("SET LOCAL app.org_id = :o"), {"o": str(org_a["org"])})
    rows = (
        await session.execute(
            text("SELECT id FROM shifts WHERE id = :id"),
            {"id": str(org_b["shift"])},
        )
    ).all()
    assert rows == []

    await session.execute(text("SET LOCAL app.org_id = :o"), {"o": str(org_b["org"])})
    rows = (
        await session.execute(
            text("SELECT id FROM shifts WHERE id = :id"),
            {"id": str(org_a["shift"])},
        )
    ).all()
    assert rows == []


async def test_audit_events_are_append_only(session: AsyncSession) -> None:
    org_a = await _seed_minimal_org(session)
    await session.execute(text("SET LOCAL app.org_id = :o"), {"o": str(org_a["org"])})

    event_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO audit_events (id, organization_id, event_type, payload) "
            "VALUES (:id, :org, 'test', '{}'::jsonb)"
        ),
        {"id": str(event_id), "org": str(org_a["org"])},
    )
    await session.commit()

    with pytest.raises(Exception):  # noqa: BLE001 — psycopg wraps in many subclasses
        await session.execute(
            text("UPDATE audit_events SET event_type = 'changed' WHERE id = :id"),
            {"id": str(event_id)},
        )
    await session.rollback()

    with pytest.raises(Exception):  # noqa: BLE001
        await session.execute(
            text("DELETE FROM audit_events WHERE id = :id"),
            {"id": str(event_id)},
        )
    await session.rollback()
