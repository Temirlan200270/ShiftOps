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

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from shiftops_api.application.templates.recurring_shifts_tick import (
    CreateRecurringShiftsTickUseCase,
)
from shiftops_api.infra.db.engine import get_sessionmaker
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
        },
    )
    return {
        "inspected": report.inspected,
        "created": report.created,
        "skipped": report.skipped,
    }


# Re-export `scheduler` from the broker module so the worker entrypoint
# (`taskiq scheduler ...`) can find the `LabelScheduleSource`.
__all__ = ["recurring_shifts_tick"]


# Defensive import: the worker might import only `infra.queue` (via the
# `import_tasks()` hook) — a side-effect import here registers the cron
# task on the same broker instance.
_ = TaskiqScheduler  # silence unused-import linters
_ = LabelScheduleSource
