"""Per-chat token bucket for outgoing Telegram messages.

Telegram allows up to 30 messages/sec globally and ~1/sec to the same chat
(soft limit). Going beyond gets you 429 and a `retry_after` payload that the
queue then has to honour.

We pre-empt this with a Redis token bucket keyed on chat_id. The bucket is
shared across worker processes so horizontal scaling remains correct.

Algorithm: classic token bucket with `capacity` tokens, refilled at `rate`
tokens/sec, evaluated lazily.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as redis_async

from shiftops_api.config import get_settings

_LUA_TAKE = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]) or capacity
local ts = tonumber(data[2]) or now

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_after = (1 - tokens) / rate
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 60)
return {allowed, tostring(retry_after)}
"""


@dataclass(frozen=True, slots=True)
class TakeResult:
    allowed: bool
    retry_after_seconds: float


class TelegramChatRateLimiter:
    def __init__(
        self,
        redis_client: redis_async.Redis | None = None,
        capacity: int = 1,
        rate: float = 1.0,  # tokens/sec
    ) -> None:
        self._redis = redis_client or redis_async.from_url(get_settings().redis_url)
        self._capacity = capacity
        self._rate = rate
        self._lua = self._redis.register_script(_LUA_TAKE)

    async def take(self, chat_id: int) -> TakeResult:
        now = time.monotonic()
        key = f"tg_rate:{chat_id}"
        result = await self._lua(
            keys=[key],
            args=[self._capacity, self._rate, f"{now:.3f}"],
        )
        allowed_raw, retry_raw = result
        return TakeResult(
            allowed=int(allowed_raw) == 1,
            retry_after_seconds=float(retry_raw),
        )
