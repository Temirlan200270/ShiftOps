"""Perceptual-hash anti-fake pipeline.

Why phash and not EXIF: EXIF is trivially stripped or spoofed; perceptual hash
captures visual content. We compare the new photo against the last N photos of
the same `(template_task_id, location_id)`. Two near-identical photos imply
either:
- the operator re-submitted yesterday's photo, OR
- the camera angle is naturally identical (e.g. a fixed shot of the bar
  surface).

We do not auto-reject — we mark `suspicious=true` and let the admin decide.
This was a conscious choice in PRD §5.3 to avoid false-positive frustration.
"""

from __future__ import annotations

import io
import uuid

import imagehash
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.db.models import Attachment, Shift, TaskInstance


def compute_phash(image_bytes: bytes) -> str:
    """Return the 64-bit perceptual hash as a 16-character hex string.

    `imagehash.phash` returns 8x8 = 64 bits by default — we keep the default;
    increasing precision overfits to noise (per imagehash docs).
    """
    image = Image.open(io.BytesIO(image_bytes))
    image.load()  # force decode now so we can close the buffer eagerly
    h = imagehash.phash(image)
    return str(h)


def hamming_distance(a: str, b: str) -> int:
    """Hamming distance between two 16-char hex perceptual hashes."""
    if len(a) != len(b):
        raise ValueError("phash length mismatch")
    return bin(int(a, 16) ^ int(b, 16)).count("1")


async def find_similar(
    *,
    session: AsyncSession,
    template_task_id: uuid.UUID,
    location_id: uuid.UUID,
    phash_hex: str,
    threshold: int,
    lookback: int,
) -> Attachment | None:
    """Return a previous attachment whose phash is within `threshold` bits.

    We restrict comparison to photos of the *same* template task at the *same*
    location, which avoids cross-task false positives ("clean glasses"
    looking like "clean countertop").
    """
    stmt = (
        select(Attachment)
        .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
        .join(Shift, Shift.id == TaskInstance.shift_id)
        .where(
            TaskInstance.template_task_id == template_task_id,
            Shift.location_id == location_id,
            Attachment.phash.is_not(None),
        )
        .order_by(Attachment.captured_at_server.desc())
        .limit(lookback)
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        if row.phash is None:
            continue
        if hamming_distance(row.phash, phash_hex) <= threshold:
            return row
    return None
