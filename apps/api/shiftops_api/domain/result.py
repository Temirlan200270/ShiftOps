"""`Result` type — small Either-like wrapper used to model business failures
explicitly instead of raising exceptions.

Why: business validation errors aren't exceptional — they are expected
outcomes. We want callers to acknowledge them with the type system.

Usage:

    def start_shift(...) -> Result[Shift, DomainError]:
        if shift.status != "scheduled":
            return Failure(DomainError("shift_not_scheduled"))
        return Success(shift)

    match start_shift():
        case Success(value=shift):
            ...
        case Failure(error=err):
            ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Success(Generic[T]):
    value: T


@dataclass(frozen=True, slots=True)
class Failure(Generic[E]):
    error: E


Result = Success[T] | Failure[E]


@dataclass(frozen=True, slots=True)
class DomainError:
    """Canonical business-level failure description.

    `code` is a stable enum-like string the API surfaces to clients (and i18n
    translates). `message` is for logs.
    """

    code: str
    message: str = ""
    details: dict[str, str] | None = None
