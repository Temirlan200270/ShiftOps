"""Media proxy endpoint.

Frontend never sees the storage provider directly — it always asks our API for
a URL, and we either redirect or stream from Telegram / R2.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser, require_user
from shiftops_api.application.media.get_media_url import GetMediaUrlUseCase
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.storage.provider import get_storage_provider

router = APIRouter()


@router.get("/{attachment_id}")
async def proxy_media(
    attachment_id: UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    use_case = GetMediaUrlUseCase(session=session, storage=get_storage_provider())
    result = await use_case.execute(attachment_id=attachment_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return RedirectResponse(url=result, status_code=status.HTTP_302_FOUND)
