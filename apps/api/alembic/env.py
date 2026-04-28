"""Alembic environment.

Uses **sync** ``psycopg`` (``DATABASE_URL_SYNC``, or ``ALEMBIC_DATABASE_URL`` if set).

**Fly.io + free Supabase:** use **pooler** hosts only (Session :5432 for sync). Direct
``db.<ref>.supabase.co`` is often **IPv6-only**; Fly machines may not reach it without Supabase
IPv4 add-on — do not rely on Direct for ``fly ssh … alembic``.

**``ALEMBIC_DATABASE_URL``** (optional): Direct URI for running Alembic **on a dev machine or CI**
with IPv6. ``sslmode=require`` is appended only for Supabase hostnames, not for ``localhost``/Docker
Postgres (CI uses plain TCP without SSL).

**``Tenant or user not found``** on the pooler: reset the DB password in Supabase and paste fresh
Session + Transaction URIs from the dashboard.
"""

from __future__ import annotations

from logging.config import fileConfig
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from shiftops_api.config.settings import get_settings
from shiftops_api.infra.db.base import Base
from shiftops_api.infra.db import models  # noqa: F401  (register models)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _ensure_sync_driver(dsn: str) -> str:
    """Force psycopg (v3) for sync migrations.

    If the URL omits the driver (e.g. `postgresql://...`), SQLAlchemy defaults to
    `psycopg2`, which we intentionally do not ship in the API image.
    """

    p = urlparse(dsn)
    if p.scheme in ("postgres", "postgresql"):
        return urlunparse(p._replace(scheme="postgresql+psycopg"))
    if p.scheme in ("postgresql+psycopg2", "postgresql+psycopg2cffi"):
        return urlunparse(p._replace(scheme="postgresql+psycopg"))
    return dsn


def _ensure_sslmode_for_supabase(dsn: str) -> str:
    """Add sslmode=require for Supabase pooler/direct hosts. Skip for local Postgres (CI, Docker)."""
    p = urlparse(dsn)
    if p.scheme not in ("postgresql", "postgresql+psycopg", "postgres"):
        return dsn
    host = (p.hostname or "").lower()
    if "supabase" not in host:
        return dsn
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    lower = {k.lower() for k, _ in q}
    if "sslmode" not in lower:
        q.append(("sslmode", "require"))
    return urlunparse(p._replace(query=urlencode(q)))


def get_url() -> str:
    s = get_settings()
    raw = (s.alembic_database_url or s.database_url_sync).strip()
    if not raw:
        msg = "Set DATABASE_URL_SYNC or ALEMBIC_DATABASE_URL (see shiftops_api.config.settings)."
        raise RuntimeError(msg)
    return _ensure_sslmode_for_supabase(_ensure_sync_driver(raw))


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        get_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
