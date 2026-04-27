"""Shift score computation.

Documented in `docs/SCORE_FORMULA.md`. Pure function; no IO.

Returns a ``ShiftScoreResult`` carrying both the headline number and the four
component scores. The breakdown lets the UI explain *why* a shift got the
score it got — without explanation, employees treat the number as a punch
in the face. With it, they treat it as a checklist of "what to fix next time".

Versioning
----------
``SCORE_FORMULA_VERSION`` increments whenever weights or component
definitions change. Each closed shift persists the version it was scored
with (``shifts.score_formula_version``); historical scores never silently
shift under employees when we tweak the formula.

Add a new version like this:
    1. Define ``def _v2(inputs)`` returning a ``ShiftScoreResult``.
    2. Add it to ``_VERSIONS`` mapping.
    3. Bump ``SCORE_FORMULA_VERSION`` to 2 — new shifts now use ``_v2``.
    4. Old shifts continue to use ``_v1`` because their stored version is 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

SCORE_FORMULA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ShiftScoreInputs:
    total_tasks: int
    done_or_waived: int
    critical_total: int
    critical_done_or_waived: int
    photo_total: int
    photo_unique: int
    scheduled_end: datetime
    actual_end: datetime


@dataclass(frozen=True, slots=True)
class ShiftScoreBreakdown:
    """Component scores in [0, 1]; multiply by weight to get points.

    Stored at full Decimal precision (no pre-rounding) so the breakdown can
    always reconstruct the headline total exactly. Display callers round at
    the end via the ``points`` helper or with their own quantize.
    """

    completion: Decimal
    critical_compliance: Decimal
    timeliness: Decimal
    photo_quality: Decimal


@dataclass(frozen=True, slots=True)
class ShiftScoreResult:
    total: Decimal
    breakdown: ShiftScoreBreakdown
    formula_version: int

    @property
    def points(self) -> dict[str, Decimal]:
        """How many of the 100 points each component contributed.

        Sum of the four returned values equals ``self.total`` exactly (both
        rounded to two decimals via the same helper). UI uses this for
        tooltips like ``Completion: 47.50 / 50``.
        """
        # Compute and round in one pass so display rounding doesn't drift
        # away from the headline total.
        return {
            "completion": _round2(self.breakdown.completion * Decimal("50")),
            "critical_compliance": _round2(self.breakdown.critical_compliance * Decimal("25")),
            "timeliness": _round2(self.breakdown.timeliness * Decimal("15")),
            "photo_quality": _round2(self.breakdown.photo_quality * Decimal("10")),
        }


_TWO_DP = Decimal("0.01")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _ratio(numerator: int, denominator: int, *, default_if_zero_denom: Decimal) -> Decimal:
    if denominator <= 0:
        return default_if_zero_denom
    # Decimal division is more precise than float here and avoids the 0.1
    # binary-rounding error showing up in audit logs.
    return Decimal(numerator) / Decimal(denominator)


def _timeliness_v1(scheduled_end: datetime, actual_end: datetime) -> Decimal:
    # Use whole-second integers so float -> Decimal conversion never injects
    # binary-rounding noise (Decimal(0.1) is 28 significant digits long).
    delta = actual_end - scheduled_end
    delay_seconds = max(0, int(delta.total_seconds()))
    if delay_seconds == 0:
        return Decimal("1")
    # Linear ramp 1 -> 0 over a 2-hour overrun window.
    timeliness = Decimal("1") - Decimal(delay_seconds) / Decimal("7200")
    return max(Decimal("0"), timeliness)


def _v1(inputs: ShiftScoreInputs) -> ShiftScoreResult:
    if inputs.total_tasks <= 0:
        zero_breakdown = ShiftScoreBreakdown(
            completion=Decimal("0"),
            critical_compliance=Decimal("0"),
            timeliness=Decimal("0"),
            photo_quality=Decimal("0"),
        )
        return ShiftScoreResult(
            total=Decimal("0.00"),
            breakdown=zero_breakdown,
            formula_version=1,
        )

    completion = _ratio(
        inputs.done_or_waived, inputs.total_tasks, default_if_zero_denom=Decimal("0")
    )
    critical_compliance = (
        Decimal("1")
        if inputs.critical_total == 0
        else (
            Decimal("1")
            if inputs.critical_done_or_waived == inputs.critical_total
            else Decimal("0")
        )
    )
    photo_quality = _ratio(
        inputs.photo_unique, inputs.photo_total, default_if_zero_denom=Decimal("1")
    )
    timeliness = _timeliness_v1(inputs.scheduled_end, inputs.actual_end)

    total_unrounded = (
        Decimal("100")
        * (
            Decimal("0.50") * completion
            + Decimal("0.25") * critical_compliance
            + Decimal("0.15") * timeliness
            + Decimal("0.10") * photo_quality
        )
    )

    return ShiftScoreResult(
        total=_round2(total_unrounded),
        breakdown=ShiftScoreBreakdown(
            completion=completion,
            critical_compliance=critical_compliance,
            timeliness=timeliness,
            photo_quality=photo_quality,
        ),
        formula_version=1,
    )


_VERSIONS: dict[int, Callable[[ShiftScoreInputs], ShiftScoreResult]] = {
    1: _v1,
}


def compute_score(
    inputs: ShiftScoreInputs, *, version: int = SCORE_FORMULA_VERSION
) -> ShiftScoreResult:
    """Compute the score using the requested formula version.

    Pass ``version`` explicitly when re-rendering historical shifts; default
    is the latest. ``KeyError`` raised for unknown versions — fail-loud so we
    notice if a deployed binary is older than a row in the DB.
    """
    try:
        impl = _VERSIONS[version]
    except KeyError as exc:
        raise ValueError(f"unknown score formula version: {version}") from exc
    return impl(inputs)
