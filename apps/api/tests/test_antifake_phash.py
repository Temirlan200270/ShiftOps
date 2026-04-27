"""Anti-fake perceptual-hash smoke tests."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from shiftops_api.infra.antifake.phash import compute_phash, hamming_distance


def _generate_image(seed: int, *, size: int = 256) -> bytes:
    img = Image.new("RGB", (size, size), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i in range(0, size, 8):
        draw.line([(i, 0), (i, size)], fill=((i + seed) % 256, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_phash_is_stable_for_same_image() -> None:
    image = _generate_image(seed=1)
    assert compute_phash(image) == compute_phash(image)


def test_phash_is_close_for_minor_perturbation() -> None:
    # The same image re-encoded at slightly different quality should keep
    # phash distance very small.
    image_a = _generate_image(seed=2)
    a_phash = compute_phash(image_a)

    img = Image.open(io.BytesIO(image_a))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    re_encoded = buf.getvalue()

    assert hamming_distance(a_phash, compute_phash(re_encoded)) <= 5


def test_phash_is_far_for_different_images() -> None:
    a = compute_phash(_generate_image(seed=1))
    b = compute_phash(_generate_image(seed=200))
    # 64-bit hash: unrelated scenes should differ by several bits. Threshold is
    # not tight — Pillow/ImageHash can yield ~6 on some Linux CI matrices.
    assert hamming_distance(a, b) >= 6
