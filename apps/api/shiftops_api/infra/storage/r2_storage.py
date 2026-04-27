"""Cloudflare R2 implementation of `StorageProvider` — V2 path.

Stubbed for V0; will be fleshed out when we migrate. Keeping the file in tree
guarantees the abstraction is honoured (tests can already import the symbol)
and that the migration plan in STORAGE.md is more than a wish.
"""

from __future__ import annotations

from .interface import AttachmentRef, StorageProvider, UploadFailed


class R2Storage(StorageProvider):
    def __init__(self) -> None:
        from shiftops_api.config import get_settings

        settings = get_settings()
        if not settings.r2_account_id or not settings.r2_bucket:
            raise UploadFailed("R2 storage selected but credentials missing")
        # V2 will lazily initialise an aioboto3 client here; intentionally not
        # done in V0 to keep imports lightweight.
        self._configured = True

    async def upload(self, file: bytes, mime: str, meta: dict[str, str]) -> AttachmentRef:
        raise UploadFailed("R2Storage.upload is V2 — not yet implemented")

    async def get_url(self, ref: AttachmentRef, ttl_seconds: int = 3600) -> str:
        raise UploadFailed("R2Storage.get_url is V2 — not yet implemented")
