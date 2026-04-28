"""Regression: Supabase transaction pooler + asyncpg prepared statement cache."""

from __future__ import annotations

from shiftops_api.infra.db import engine as engine_module


def test_statement_cache_disabled_for_supabase_transaction_pooler_port() -> None:
    url = "postgresql+asyncpg://user:pass@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
    assert engine_module._asyncpg_connect_args(url) == {"statement_cache_size": 0}


def test_statement_cache_disabled_when_host_contains_pooler() -> None:
    url = "postgresql+asyncpg://user:pass@custom-pooler.example.com:5432/postgres"
    assert engine_module._asyncpg_connect_args(url) == {"statement_cache_size": 0}


def test_empty_connect_args_for_direct_postgres() -> None:
    url = "postgresql+asyncpg://shiftops:shiftops@postgres:5432/shiftops"
    assert engine_module._asyncpg_connect_args(url) == {}
