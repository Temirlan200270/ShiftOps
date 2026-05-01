"""Heuristic checks beyond perceptual hash (e.g. nearly black frames)."""

from __future__ import annotations

import io

from PIL import Image, ImageStat


def mean_luminance_255(image_bytes: bytes) -> float:
    """Mean grayscale value on a 0–255 scale."""

    with Image.open(io.BytesIO(image_bytes)) as im:
        gray = im.convert("L")
        stat = ImageStat.Stat(gray)
        return float(stat.mean[0])


def is_low_luminance_photo(image_bytes: bytes, *, min_mean: float) -> bool:
    """True when the frame is suspiciously dark (covered lens, black photo, etc.)."""

    if min_mean <= 0:
        return False
    try:
        return mean_luminance_255(image_bytes) < min_mean
    except OSError:
        return False
