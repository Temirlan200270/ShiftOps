"""Async SQLAlchemy engine + session factory.

The middleware in `infra/db/tenant.py` wraps each request in a transaction and
sets `app.org_id` so RLS policies can isolate tenants.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shiftops_api.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _asyncpg_connect_args(database_url: str) -> dict[str, object]:
    """asyncpg caches prepared statements per connection.

    Supabase (and other setups) route ``DATABASE_URL`` through **PgBouncer**
    in *transaction* or *statement* pool mode. The same logical server-side
    connection can be handed to different clients between transactions, so
    prepared statement names from a previous checkout collide →
    ``DuplicatePreparedStatementError`` on ``select pg_catalog.version()`` etc.

    Disabling the statement cache is the fix recommended by asyncpg when
    PgBouncer cannot preserve prepared statements (see error hint in logs).
    Direct Postgres (local Docker, port 5432) keeps the default cache.
    """

    try:
        parsed = make_url(database_url)
    except Exception:
        return {}
    host = (parsed.host or "").lower()
    if parsed.port == 6543 or "pooler" in host:
        return {"statement_cache_size": 0}
    return {}


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = _asyncpg_connect_args(settings.database_url)
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            # Supabase pooler closes idle connections after ~30 minutes; if we
            # hold one longer we'd hit a stale-socket error. Recycle just
            # before that to avoid the round-trip.
            pool_recycle=settings.db_pool_recycle_seconds,
            connect_args=connect_args,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
