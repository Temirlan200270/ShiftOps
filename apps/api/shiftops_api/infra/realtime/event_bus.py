"""Tiny Redis pub/sub event bus for the live monitor.

Scope
-----
This is **not** a general-purpose message bus. It carries low-volume,
fire-and-forget UI events:

- ``shift.opened`` — operator hit Start
- ``task.completed`` — task moved to done (with ``suspicious`` bit)
- ``shift.closed`` — final summary
- ``waiver.requested`` / ``waiver.decided`` — admin action triggers

Channel layout: one channel per organisation (``shiftops:rt:org:<uuid>``).
That gives strict tenant isolation at the transport layer — a
subscriber from org A literally never receives messages from org B
because they never even subscribe to that channel.

Why not TaskIQ or another queue
-------------------------------
TaskIQ is for *durable* work (Telegram messages, retries, rate limits).
Live-monitor events are ephemeral; a missed message is acceptable
because the next event repaints the dashboard. Pub/sub is therefore
the correct primitive: zero retention, no consumer-group bookkeeping.

Connection lifecycle
--------------------
We keep one ``redis.asyncio`` client per process and reuse it across
publishes. Subscribers (the WebSocket handler) ask for a fresh
``PubSub`` instance and clean it up themselves; this is the standard
``redis-py`` pattern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import redis.asyncio as redis_async

from shiftops_api.config import get_settings


_log = logging.getLogger(__name__)
_CHANNEL_PREFIX = "shiftops:rt:org:"


def _channel(organization_id: uuid.UUID) -> str:
    return f"{_CHANNEL_PREFIX}{organization_id}"


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """Wire-shape for a UI event.

    ``type`` is the discriminator the frontend keys on. ``data`` carries
    a flat object — we never nest more than one level deep so JSON.parse
    in the browser is cheap and the live monitor's reducer stays small.
    """

    type: str
    data: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data}, default=str)

    @classmethod
    def from_json(cls, payload: str) -> "RealtimeEvent":
        body = json.loads(payload)
        return cls(type=str(body.get("type", "")), data=dict(body.get("data") or {}))


class _EventBus:
    def __init__(self, *, url: str) -> None:
        self._url = url
        self._client: redis_async.Redis | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> redis_async.Redis:
        # Lazy connect with a lock so concurrent publishers don't open
        # N clients on the first hit. ``decode_responses`` keeps the
        # subscribe API ergonomic — we just deal in str payloads.
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = redis_async.from_url(
                        self._url,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_keepalive=True,
                        health_check_interval=30,
                    )
        return self._client

    async def publish(self, *, organization_id: uuid.UUID, event: RealtimeEvent) -> None:
        try:
            client = await self._get_client()
            await client.publish(_channel(organization_id), event.to_json())
        except Exception:  # noqa: BLE001 — never fail the caller because of a transport hiccup
            _log.warning(
                "realtime.publish.failed",
                extra={"event": event.type, "org": str(organization_id)},
                exc_info=True,
            )

    async def subscribe(self, *, organization_id: uuid.UUID) -> AsyncIterator[RealtimeEvent]:
        client = await self._get_client()
        pubsub = client.pubsub()
        await pubsub.subscribe(_channel(organization_id))
        try:
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue  # subscribe ack and similar — ignore
                payload = message.get("data")
                if not isinstance(payload, str):
                    continue
                try:
                    yield RealtimeEvent.from_json(payload)
                except (ValueError, TypeError):
                    _log.warning("realtime.malformed_message", extra={"raw": payload[:200]})
        finally:
            try:
                await pubsub.unsubscribe(_channel(organization_id))
            finally:
                await pubsub.close()

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


_bus: _EventBus | None = None


def get_event_bus() -> _EventBus:
    global _bus
    if _bus is None:
        _bus = _EventBus(url=get_settings().redis_url)
    return _bus


async def publish_event(
    *,
    organization_id: uuid.UUID,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Convenience wrapper used by use-case dispatchers.

    Catching is deferred to ``_EventBus.publish`` so a Redis blip never
    breaks the calling request.
    """

    await get_event_bus().publish(
        organization_id=organization_id,
        event=RealtimeEvent(type=event_type, data=data),
    )
