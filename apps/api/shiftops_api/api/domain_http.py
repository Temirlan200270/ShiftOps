"""Map :class:`~shiftops_api.domain.result.DomainError` to HTTP status codes.

Routers should prefer :func:`raise_for_domain_failure` over ad-hoc ``if code ==
...`` blocks so stable ``code`` strings stay consistent with the JSON error
envelope handled by :func:`shiftops_api.api.errors.install_error_handlers`.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status

from shiftops_api.domain.result import DomainError, Failure, Result, Success

# Codes that must return specific HTTP statuses — anything else defaults to 400.
_STATUS_BY_CODE: dict[str, int] = {
    "not_your_shift": status.HTTP_403_FORBIDDEN,
    "insufficient_role": status.HTTP_403_FORBIDDEN,
    "cannot_manage_self": status.HTTP_403_FORBIDDEN,
    "cannot_manage_super_admin": status.HTTP_403_FORBIDDEN,
    "cannot_change_owner_role": status.HTTP_403_FORBIDDEN,
    "not_an_admin": status.HTTP_403_FORBIDDEN,
    # 404
    "user_not_found": status.HTTP_404_NOT_FOUND,
    "template_not_found": status.HTTP_404_NOT_FOUND,
    "shift_not_found": status.HTTP_404_NOT_FOUND,
    "task_not_found": status.HTTP_404_NOT_FOUND,
    "no_shift": status.HTTP_404_NOT_FOUND,
    "organization_not_found": status.HTTP_404_NOT_FOUND,
    "organization_inactive": status.HTTP_404_NOT_FOUND,
    "organization_already_deleted": status.HTTP_409_CONFLICT,
    "organization_unavailable": status.HTTP_401_UNAUTHORIZED,
    "org_not_found": status.HTTP_404_NOT_FOUND,
    "location_not_found": status.HTTP_404_NOT_FOUND,
    "admin_not_found": status.HTTP_404_NOT_FOUND,
    # 409
    "template_in_use": status.HTTP_409_CONFLICT,
    "invite_already_used": status.HTTP_409_CONFLICT,
    "already_active_member": status.HTTP_409_CONFLICT,
    "shift_not_scheduled": status.HTTP_409_CONFLICT,
    "shift_not_active": status.HTTP_409_CONFLICT,
    "shift_taken": status.HTTP_409_CONFLICT,
    "shift_not_claimed": status.HTTP_409_CONFLICT,
    # swap
    "swap_request_not_found": status.HTTP_404_NOT_FOUND,
    "swap_not_counterparty": status.HTTP_403_FORBIDDEN,
    "swap_not_proposer": status.HTTP_403_FORBIDDEN,
    "swap_not_pending": status.HTTP_409_CONFLICT,
    "swap_shifts_changed": status.HTTP_409_CONFLICT,
    "swap_duplicate_pending": status.HTTP_409_CONFLICT,
    "invalid_direction": status.HTTP_400_BAD_REQUEST,
    "swap_link_not_scheduled": status.HTTP_409_CONFLICT,
    "swap_link_shift_unassigned": status.HTTP_409_CONFLICT,
}

_DEFAULT_STATUS = status.HTTP_400_BAD_REQUEST


def http_status_for_domain_code(code: str) -> int:
    return _STATUS_BY_CODE.get(code, _DEFAULT_STATUS)


def http_exception_for_domain_error(err: DomainError) -> HTTPException:
    detail = f"{err.code}: {err.message}" if err.message else err.code
    return HTTPException(status_code=http_status_for_domain_code(err.code), detail=detail)


def raise_for_domain_failure(result: Failure[DomainError]) -> NoReturn:
    raise http_exception_for_domain_error(result.error)


def unwrap_domain_result[T](result: Result[T, DomainError]) -> T:
    match result:
        case Success(value=value):
            return value
        case Failure(error=err):
            raise http_exception_for_domain_error(err)
