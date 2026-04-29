"""Standardised JSON error envelope.

Why this exists
---------------
FastAPI's default `HTTPException` serialises as ``{"detail": "..."}`` — the
"detail" field can be a string, list, or object depending on the source
(validation errors are nested objects, raised exceptions are strings). This
forces clients to special-case three response shapes.

We standardise on::

    {
      "code": "invalid_init_data",   # stable machine-readable identifier
      "message": "HMAC mismatch"     # human-readable English string
    }

`code` is the contract the frontend keys on (``HandshakeError.code`` etc.);
`message` is for logs and developer-facing UI. User-facing copy is *always*
chosen on the frontend from i18n bundles, never from this `message`.

Convention for raising:
    raise HTTPException(status_code=409, detail="shift_already_active")

The handler below splits the original ``detail`` on ":" — anything before is
the code, anything after is the message. This lets use cases continue to
raise via plain strings without coupling to this module.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _split_code_message_details(detail: Any) -> tuple[str, str, Any | None]:
    if isinstance(detail, str):
        if ":" in detail:
            code, _, message = detail.partition(":")
            return code.strip(), message.strip(), None
        return detail, detail, None
    # Validation errors arrive as a list of dicts; collapse them.
    if isinstance(detail, list):
        return (
            "validation_error",
            "; ".join(
            str(item.get("msg", item)) if isinstance(item, dict) else str(item)
            for item in detail
            ),
            detail,
        )
    if isinstance(detail, dict):
        code = str(detail.get("code") or "error")
        message = str(detail.get("message") or detail)
        details = detail.get("details")
        return code, message, details if details is not None else detail
    return "error", str(detail), None


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message, details = _split_code_message_details(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message, "details": details},
        headers=getattr(exc, "headers", None),
    )


async def _validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    code, message, details = _split_code_message_details(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"code": code, "message": message, "details": details},
    )


async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # We deliberately do NOT leak the str(exc) to clients in production —
    # Sentry already captured it via the SDK integration. The frontend just
    # needs a stable code so it can render a friendly toast.
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "Internal server error", "details": None},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Wire the standardised handlers onto a FastAPI app.

    Call this once during app construction. Tests can call it on a fresh app
    instance to reproduce production error rendering.
    """

    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
