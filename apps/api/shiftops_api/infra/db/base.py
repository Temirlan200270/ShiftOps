"""Declarative base for SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(DeclarativeBase):
    """Project-wide declarative base. Imported by Alembic and model modules."""

    metadata_naming_convention = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
