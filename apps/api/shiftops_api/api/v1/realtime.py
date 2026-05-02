"""Live monitor: WebSocket + active-shifts snapshot endpoint.

Authentication on the WebSocket
-------------------------------
Browsers can't set Authorization headers on a WebSocket open, so we
accept the access token in the ``token`` query parameter. The token is
validated with the same ``JwtService`` used for HTTP routes; we never
trust the connection until ``verify`` returns. Operators get a 4403
close on connect — only admin/owner subscribe to the firehose.

WebSocket protocol
------------------
Server → client: JSON frames matching :class:`RealtimeEvent`. Each
frame has ``type`` and ``data``. The stream begins with a single
``hello`` frame so the client can confirm authentication succeeded
before flipping the UI to "live".

Client → server: nothing. We only listen to upgrade pings; any client
message is ignored. Heartbeats are handled by ``ws_ping_interval`` on
the FastAPI side (uvicorn default) plus a server-pushed ``ping`` event
every 25 s if the bus is silent — that's the real keep-alive against
proxies that close idle TCP after 30 s (Vercel, Cloudflare).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from shiftops_api.application.auth.deps import CurrentUser, require_role
from shiftops_api.application.monitor.active_shifts import (
    ActiveShiftDTO,
    ListActiveShiftsUseCase,
)
from shiftops_api.application.monitor.vacant_at_risk_shifts import ListVacantAtRiskShiftsUseCase
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.auth.jwt_service import JwtError, JwtService
from shiftops_api.infra.db.engine import get_session, get_sessionmaker
from shiftops_api.infra.metrics import REALTIME_WS_CONNECTIONS
from shiftops_api.infra.realtime import RealtimeEvent, get_event_bus

router = APIRouter()

_admin_or_owner = require_role(UserRole.ADMIN, UserRole.OWNER)


class ActiveShiftOut(BaseModel):
    shift_id: UUID
    location_id: UUID
    location_name: str
    template_name: str
    operator_id: UUID
    operator_name: str
    scheduled_start: str
    scheduled_end: str
    actual_start: str | None
    progress_total: int
    progress_done: int
    progress_critical_pending: int


class VacantAtRiskOut(BaseModel):
    shift_id: UUID
    location_id: UUID
    location_name: str
    template_name: str
    scheduled_start: str
    scheduled_end: str
    station_label: str | None
    slot_index: int
    kind: Literal["overdue", "unclaimed_started", "ending_soon"]


class MonitorSnapshotOut(BaseModel):
    active: list[ActiveShiftOut]
    vacant_at_risk: list[VacantAtRiskOut]


def _map_active_rows(rows: list[ActiveShiftDTO]) -> list[ActiveShiftOut]:
    return [
        ActiveShiftOut(
            shift_id=row.shift_id,
            location_id=row.location_id,
            location_name=row.location_name,
            template_name=row.template_name,
            operator_id=row.operator_id,
            operator_name=row.operator_name,
            scheduled_start=row.scheduled_start.isoformat(),
            scheduled_end=row.scheduled_end.isoformat(),
            actual_start=row.actual_start.isoformat() if row.actual_start else None,
            progress_total=row.progress_total,
            progress_done=row.progress_done,
            progress_critical_pending=row.progress_critical_pending,
        )
        for row in rows
    ]


@router.get("/monitor-snapshot", response_model=MonitorSnapshotOut)
async def monitor_snapshot(
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> MonitorSnapshotOut:
    active_uc = ListActiveShiftsUseCase(session=session)
    vacant_uc = ListVacantAtRiskShiftsUseCase(session=session)
    a = await active_uc.execute(user=user)
    v = await vacant_uc.execute(user=user)
    if isinstance(a, Failure):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=a.error.code,
        )
    if isinstance(v, Failure):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=v.error.code,
        )
    assert isinstance(a, Success) and isinstance(v, Success)
    vacant_out = [
        VacantAtRiskOut(
            shift_id=row.shift_id,
            location_id=row.location_id,
            location_name=row.location_name,
            template_name=row.template_name,
            scheduled_start=row.scheduled_start.isoformat(),
            scheduled_end=row.scheduled_end.isoformat(),
            station_label=row.station_label,
            slot_index=row.slot_index,
            kind=row.kind,
        )
        for row in v.value
    ]
    return MonitorSnapshotOut(active=_map_active_rows(a.value), vacant_at_risk=vacant_out)


@router.get("/active-shifts", response_model=list[ActiveShiftOut])
async def list_active_shifts(
    user: CurrentUser = Depends(_admin_or_owner),
    session: AsyncSession = Depends(get_session),
) -> list[ActiveShiftOut]:
    use_case = ListActiveShiftsUseCase(session=session)
    result = await use_case.execute(user=user)
    if isinstance(result, Failure):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=result.error.code,
        )
    assert isinstance(result, Success)
    return _map_active_rows(result.value)


_log = logging.getLogger(__name__)
_HEARTBEAT_SECONDS = 25.0


@router.websocket("/ws")
async def realtime_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    try:
        payload = JwtService().verify(token)
    except JwtError as exc:
        await websocket.close(code=4401, reason=f"invalid_token:{exc}")
        return

    if payload.token_type != "access":
        await websocket.close(code=4401, reason="not_an_access_token")
        return

    if payload.role not in (UserRole.ADMIN, UserRole.OWNER):
        await websocket.close(code=4403, reason="insufficient_role")
        return

    # The DB ping is cheap and confirms the JWT's organisation actually
    # has RLS context wired in this process. Lets us reject stale tokens
    # whose org was deleted between mint and connect.
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            await websocket.close(code=1011, reason="db_unavailable")
            return

    await websocket.accept()
    REALTIME_WS_CONNECTIONS.inc()
    bus = get_event_bus()

    hello = RealtimeEvent(
        type="hello",
        data={
            "organization_id": str(payload.org),
            "role": payload.role.value,
            "server_time": datetime.now(tz=UTC).isoformat(),
        },
    )
    await websocket.send_text(hello.to_json())

    stop = asyncio.Event()

    async def heartbeat() -> None:
        # Keep the connection healthy across idle proxies. A short ping
        # frame is cheap and tells us the socket is still writable.
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                pass
            if stop.is_set():
                return
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            ping = RealtimeEvent(
                type="ping",
                data={"at": datetime.now(tz=UTC).isoformat()},
            )
            try:
                await websocket.send_text(ping.to_json())
            except Exception:  # noqa: BLE001
                stop.set()
                return

    async def relay() -> None:
        try:
            async for event in bus.subscribe(organization_id=payload.org):
                if stop.is_set():
                    return
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                try:
                    await websocket.send_text(event.to_json())
                except Exception:  # noqa: BLE001
                    stop.set()
                    return
        except Exception:  # noqa: BLE001
            _log.warning("realtime.subscribe.failed", exc_info=True)
            stop.set()

    async def listener() -> None:
        # Some browsers send periodic noop frames; we discard them.
        # Any disconnect raises and breaks us out of the gather.
        try:
            while not stop.is_set():
                await websocket.receive_text()
        except WebSocketDisconnect:
            stop.set()
        except Exception:  # noqa: BLE001
            stop.set()

    tasks = [
        asyncio.create_task(heartbeat()),
        asyncio.create_task(relay()),
        asyncio.create_task(listener()),
    ]
    try:
        # Any task finishing means the socket is closing; cancel the rest.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        REALTIME_WS_CONNECTIONS.dec()
