"""TaskIQ broker — Redis pub/sub for background notifications.

Tasks live in `infra.notifications.tasks` and `infra.media.tasks`. They are
imported here so the worker autodiscovers them.
"""

from __future__ import annotations

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from shiftops_api.config import get_settings

_settings = get_settings()

broker = ListQueueBroker(url=_settings.redis_url).with_result_backend(
    RedisAsyncResultBackend(redis_url=_settings.redis_url)
)

scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])


def import_tasks() -> None:
    """Trigger task module imports so they register with the broker."""
    from shiftops_api.infra.notifications import tasks as _notif_tasks  # noqa: F401
    from shiftops_api.infra.scheduling import tasks as _sched_tasks  # noqa: F401


import_tasks()
