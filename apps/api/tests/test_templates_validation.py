"""Validation rules for SaveTemplateUseCase that Pydantic can't enforce.

Pydantic at the HTTP boundary catches min/max length on individual fields,
but these rules apply across the payload as a whole (duplicate ids, task
count bounds) and are exercised by the use case directly. We pull the
private ``_validate`` here on purpose — it's the smallest reliable test
seam without standing up a database.
"""

from __future__ import annotations

import uuid

from shiftops_api.application.templates.dtos import (
    TemplateInputDTO,
    TemplateTaskInputDTO,
)
from shiftops_api.application.templates.save_template import (
    MAX_TASKS,
    MIN_NAME_LEN,
    _validate,
)
from shiftops_api.domain.enums import Criticality, UserRole


def _task(*, id_: uuid.UUID | None = None, title: str = "Wipe counters") -> TemplateTaskInputDTO:
    return TemplateTaskInputDTO(
        id=id_,
        title=title,
        description=None,
        criticality=Criticality.REQUIRED,
        requires_photo=False,
        requires_comment=False,
    )


def test_valid_payload_returns_none() -> None:
    payload = TemplateInputDTO(
        name="Morning shift",
        role_target=UserRole.OPERATOR,
        tasks=[_task(), _task(title="Restock napkins")],
    )
    assert _validate(payload) is None


def test_short_name_rejected() -> None:
    payload = TemplateInputDTO(
        name="ab",  # below MIN_NAME_LEN=3
        role_target=UserRole.OPERATOR,
        tasks=[_task()],
    )
    assert MIN_NAME_LEN == 3
    err = _validate(payload)
    assert err is not None and err.code == "invalid_name_length"


def test_zero_tasks_rejected() -> None:
    payload = TemplateInputDTO(
        name="Morning shift",
        role_target=UserRole.OPERATOR,
        tasks=[],
    )
    err = _validate(payload)
    assert err is not None and err.code == "invalid_task_count"


def test_too_many_tasks_rejected() -> None:
    payload = TemplateInputDTO(
        name="Morning shift",
        role_target=UserRole.OPERATOR,
        tasks=[_task() for _ in range(MAX_TASKS + 1)],
    )
    err = _validate(payload)
    assert err is not None and err.code == "invalid_task_count"


def test_short_task_title_rejected() -> None:
    payload = TemplateInputDTO(
        name="Morning shift",
        role_target=UserRole.OPERATOR,
        tasks=[_task(title="ab")],
    )
    err = _validate(payload)
    assert err is not None and err.code == "invalid_task_title"


def test_duplicate_task_ids_rejected() -> None:
    same = uuid.uuid4()
    payload = TemplateInputDTO(
        name="Morning shift",
        role_target=UserRole.OPERATOR,
        tasks=[_task(id_=same), _task(id_=same)],
    )
    err = _validate(payload)
    assert err is not None and err.code == "duplicate_task_id"


def test_whitespace_name_rejected() -> None:
    """Names like "   " should fail length after strip."""
    payload = TemplateInputDTO(
        name="     ",
        role_target=UserRole.OPERATOR,
        tasks=[_task()],
    )
    err = _validate(payload)
    assert err is not None and err.code == "invalid_name_length"
