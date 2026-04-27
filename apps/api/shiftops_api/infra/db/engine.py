"""Async SQLAlchemy engine + session factory.

The middleware in `infra/db/tenant.py` wraps each request in a transaction and
sets `app.org_id` so RLS policies can isolate tenants.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shiftops_api.config import get_settings


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
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
