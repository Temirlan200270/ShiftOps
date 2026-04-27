"""SQLAlchemy ORM models.

Importing this package registers every table on `Base.metadata`. Alembic's
`env.py` does `from shiftops_api.infra.db.base import Base` and then refers to
`Base.metadata` — so this `__init__` is what actually pulls models in.
"""

from .attachment import Attachment
from .audit_event import AuditEvent
from .location import Location
from .organization import Organization
from .shift import Shift
from .task_instance import TaskInstance
from .telegram_account import TelegramAccount
from .template import Template
from .template_task import TemplateTask
from .user import User

__all__ = [
    "Attachment",
    "AuditEvent",
    "Location",
    "Organization",
    "Shift",
    "TaskInstance",
    "TelegramAccount",
    "Template",
    "TemplateTask",
    "User",
]
