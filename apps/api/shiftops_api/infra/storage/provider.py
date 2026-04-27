"""DI binding selecting the active StorageProvider implementation.

The frontend never sees this — it always goes through `/api/v1/media/{uuid}`.
"""

from __future__ import annotations

from functools import lru_cache

from shiftops_api.config import get_settings

from .interface import StorageProvider
from .r2_storage import R2Storage
from .telegram_storage import TelegramStorage


@lru_cache(maxsize=1)
def get_storage_provider() -> StorageProvider:
    kind = get_settings().storage_provider
    if kind == "r2":
        return R2Storage()
    return TelegramStorage()


def reset_storage_provider() -> None:
    """Clear the cached provider — used in tests when env changes mid-process."""
    get_storage_provider.cache_clear()
