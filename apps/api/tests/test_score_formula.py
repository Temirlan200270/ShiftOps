"""Unit tests for the shift score formula.

Anchor cases come from docs/SCORE_FORMULA.md so docs and code can never
silently disagree. If you add a case to the docs, mirror it here in the same
PR — the test names match the bullet points in the doc 1:1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shiftops_api.domain.score import (
    SCORE_FORMULA_VERSION,
    ShiftScoreInputs,
    compute_score,
)


def _inputs(
    *,
    total: int = 20,
    done: int = 20,
    crit_total: int = 4,
    crit_done: int = 4,
    photo_total: int = 8,
    photo_unique: int = 8,
    delay: timedelta = timedelta(0),
) -> ShiftScoreInputs:
    scheduled_end = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    return ShiftScoreInputs(
        total_tasks=total,
        done_or_waived=done,
        critical_total=crit_total,
        critical_done_or_waived=crit_done,
        photo_total=photo_total,
        photo_unique=photo_unique,
        scheduled_end=scheduled_end,
        actual_end=scheduled_end + delay,
    )


def test_perfect_shift_scores_100() -> None:
    result = compute_score(_inputs())
    assert result.total == Decimal("100.00")
    assert result.formula_version == 1
    assert result.breakdown.completion == Decimal("1.00")
    assert result.breakdown.critical_compliance == Decimal("1.00")
    assert result.breakdown.timeliness == Decimal("1.00")
    assert result.breakdown.photo_quality == Decimal("1.00")


def test_one_required_missed_drops_score_to_97_5() -> None:
    # 19/20 done, all critical done, on time, all photos unique → 97.5.
    result = compute_score(_inputs(done=19))
    assert result.total == Decimal("97.50")
    assert result.breakdown.completion == Decimal("0.95")


def test_one_critical_missed_zeroes_critical_block() -> None:
    # done=19 because the missed critical is also missed for completion.
    # 0.5*0.95 + 0.25*0 + 0.15*1 + 0.10*1 = 47.5 + 0 + 15 + 10 = 72.5
    result = compute_score(_inputs(done=19, crit_done=3))
    assert result.breakdown.critical_compliance == Decimal("0.00")
    assert result.total == Decimal("72.50")


def test_two_suspicious_photos_reduce_photo_quality() -> None:
    # 8 photos total, 6 unique → photo_quality = 0.75 → 7.5/10 points.
    # 0.5*1 + 0.25*1 + 0.15*1 + 0.10*0.75 = 50+25+15+7.5 = 97.5
    result = compute_score(_inputs(photo_unique=6))
    assert result.total == Decimal("97.50")
    assert result.breakdown.photo_quality == Decimal("0.75")


def test_one_hour_overrun_halves_timeliness() -> None:
    # 2-hour ramp, 1 hour late → timeliness = 0.5 → 7.5/15 points.
    result = compute_score(_inputs(delay=timedelta(hours=1)))
    assert result.breakdown.timeliness == Decimal("0.50")
    # 0.5*1 + 0.25*1 + 0.15*0.5 + 0.10*1 = 50+25+7.5+10 = 92.5
    assert result.total == Decimal("92.50")


def test_three_hour_overrun_zeroes_timeliness() -> None:
    # Past the 2-hour window, timeliness clamps at 0.
    result = compute_score(_inputs(delay=timedelta(hours=3)))
    assert result.breakdown.timeliness == Decimal("0.00")


def test_zero_tasks_returns_zero_safely() -> None:
    # Edge case: shift with no template tasks. We don't crash; we return 0
    # so the audit log records something rather than NULL.
    result = compute_score(_inputs(total=0, done=0, crit_total=0, photo_total=0))
    assert result.total == Decimal("0.00")


def test_unknown_version_raises() -> None:
    # Forward-compatibility check: a row stored with v999 must error loudly,
    # not silently fall back to v1 (would mis-state the score).
    with pytest.raises(ValueError):
        compute_score(_inputs(), version=999)


def test_constant_matches_implemented_version() -> None:
    # Guards against bumping the constant without adding a new impl.
    result = compute_score(_inputs())
    assert result.formula_version == SCORE_FORMULA_VERSION


def test_points_helper_sums_to_total() -> None:
    # The breakdown.points helper must exactly reconstruct the headline
    # score, otherwise the UI would show inconsistent numbers.
    result = compute_score(_inputs(done=18, photo_unique=7, delay=timedelta(minutes=30)))
    points = result.points
    summed = sum(points.values())
    assert summed == result.total, f"breakdown sum {summed} != total {result.total}"
