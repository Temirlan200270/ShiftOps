"""TaskIQ periodic tasks for shift recurrence.

The ``recurring_shifts_tick`` task fires every minute. Each invocation
opens its own DB session (we cannot share a request session here, this
runs in the worker process), constructs the use case, and commits.

We deliberately avoid TaskIQ result tracking (``Depends`` + result
backend) — the tick is a sweep; if it crashes we'd rather see a
Sentry breadcrumb and let the next minute's tick recover than block
the broker on a stuck retry chain.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from sqlalchemy import delete, select
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from shiftops_api.application.monitor.vacant_before_start_alert_tick import (
    VacantBeforeStartAlertTickUseCase,
)
from shiftops_api.application.templates.recurring_shifts_tick import (
    CreateRecurringShiftsTickUseCase,
)
from shiftops_api.config import get_settings
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import Organization
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.metrics import (
    RECURRING_SHIFTS_CREATED_TOTAL,
    RECURRING_TICK_CREATED_LAST,
    RECURRING_TICK_TEMPLATES_VISIBLE,
)
from shiftops_api.infra.queue import broker

_log = logging.getLogger(__name__)


@broker.task(
    task_name="shiftops.recurring_shifts_tick",
    schedule=[{"cron": "* * * * *"}],
)
async def recurring_shifts_tick() -> dict[str, int]:
    """Cron: every minute. Materialises shifts whose recurrence window
    is open right now. Returns a tiny report for logs / dashboards.
    """

    factory = get_sessionmaker()
    async with factory() as session:
        use_case = CreateRecurringShiftsTickUseCase(session=session)
        report = await use_case.execute()

    # Canary metrics: if FORCE RLS blocks the worker, inspected will drop to 0.
    RECURRING_TICK_TEMPLATES_VISIBLE.set(report.inspected)
    RECURRING_TICK_CREATED_LAST.set(report.created)
    if report.created:
        RECURRING_SHIFTS_CREATED_TOTAL.inc(report.created)

    _log.info(
        "recurring.tick.summary",
        extra={
            "inspected": report.inspected,
            "created": report.created,
            "skipped": report.skipped,
            "aborted_expired_vacant": report.aborted_expired_vacant,
        },
    )
    return {
        "inspected": report.inspected,
        "created": report.created,
        "skipped": report.skipped,
        "aborted_expired_vacant": report.aborted_expired_vacant,
    }


@broker.task(
    task_name="shiftops.vacant_before_start_alert_tick",
    schedule=[{"cron": "* * * * *"}],
)
async def vacant_before_start_alert_tick() -> dict[str, int]:
    """Cron: every minute. Ping admin chat if a vacant pool slot opens within the window."""

    settings = get_settings()
    redis = redis_async.from_url(settings.redis_url)
    factory = get_sessionmaker()
    try:
        async with factory() as session:
            use_case = VacantBeforeStartAlertTickUseCase(session=session, redis=redis)
            report = await use_case.execute()
    finally:
        await redis.aclose()

    _log.info(
        "vacant_before_start_alert.summary",
        extra={
            "candidates": report.candidates,
            "sent": report.sent,
            "skipped_no_admin_chat": report.skipped_no_admin_chat,
        },
    )
    return {
        "candidates": report.candidates,
        "sent": report.sent,
        "skipped_no_admin_chat": report.skipped_no_admin_chat,
    }


@broker.task(
    task_name="shiftops.purge_deleted_orgs_tick",
    schedule=[{"cron": "27 4 * * *"}],
)
async def purge_deleted_orgs_tick() -> dict[str, int]:
    """Daily: hard-delete organizations past the soft-delete retention window."""

    settings = get_settings()
    cutoff = datetime.now(tz=UTC) - timedelta(days=settings.org_deletion_retention_days)
    factory = get_sessionmaker()
    async with factory() as session:
        await enter_privileged_rls_mode(session, reason="purge_deleted_orgs_list")
        ids = list(
            (
                await session.execute(
                    select(Organization.id).where(
                        Organization.deleted_at.isnot(None),
                        Organization.deleted_at <= cutoff,
                    )
                )
            ).scalars().all()
        )
        await session.commit()

    purged = 0
    for oid in ids:
        async with factory() as s:
            await enter_privileged_rls_mode(s, reason="purge_deleted_org")
            try:
                await s.execute(delete(Organization).where(Organization.id == oid))
                await s.commit()
                purged += 1
            except Exception:
                await s.rollback()
                _log.warning("purge_org_failed", extra={"organization_id": str(oid)})

    _log.info(
        "purge_deleted_orgs.summary",
        extra={"candidates": len(ids), "purged": purged},
    )
    return {"candidates": len(ids), "purged": purged}


# Re-export `scheduler` from the broker module so the worker entrypoint
# (`taskiq scheduler ...`) can find the `LabelScheduleSource`.
__all__ = ["purge_deleted_orgs_tick", "recurring_shifts_tick"]


# Defensive import: the worker might import only `infra.queue` (via the
# `import_tasks()` hook) — a side-effect import here registers the cron
# task on the same broker instance.
_ = TaskiqScheduler  # silence unused-import linters
_ = LabelScheduleSource
