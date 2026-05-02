"""Unit tests for :mod:`shiftops_api.application.analytics.overview`.

Why mostly pure tests
---------------------
The use case is a thin coordinator over SQLAlchemy queries that lean
heavily on Postgres functions (``EXTRACT``, ``timezone()``, ``EPOCH FROM``).
Spinning a real Postgres for each test would be slow; SQLite can't even
parse those calls. The fragile parts that we have actually shipped bugs
in:

* density-flag thresholds (off-by-one between "low" and "ok"),
* date-range validation,
* compare-mode plumbing (``previous`` field shape).

…all live in pure code paths that can be tested directly.

End-to-end coverage of the SQL itself lives in ``test_rls_isolation.py``-
style integration tests that we run when a Postgres container is wired
up in CI.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from shiftops_api.application.analytics.overview import (
    DEFAULT_VIOLATORS_LIMIT,
    MAX_DAYS,
    AnalyticsOverviewUseCase,
    AntifakeBlock,
    CriticalityRow,
    HeatmapCell,
    KpiBlock,
    LocationRow,
    PostRow,
    RoleSplitBlock,
    SlaBlock,
    TemplateRow,
    ViolatorRow,
)
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success

# --- Fixtures / helpers ----------------------------------------------------


def _user(role: UserRole = UserRole.OWNER) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=role,
        tg_user_id=None,
    )


def _kpi(total: int = 0, clean: int = 0, viol: int = 0, avg: float | None = None) -> KpiBlock:
    avg_dec = Decimal(str(avg)) if avg is not None else None
    return KpiBlock(
        shifts_closed=total,
        shifts_clean=clean,
        shifts_with_violations=viol,
        average_score=avg_dec,
        cleanliness_rate=(
            (Decimal(clean) / Decimal(total)).quantize(Decimal("0.0001"))
            if total > 0
            else None
        ),
    )


def _violator(*, total: int = 5, viol: int = 1) -> ViolatorRow:
    return ViolatorRow(
        user_id=uuid.uuid4(),
        full_name="Alex",
        role=UserRole.OPERATOR.value,
        shifts_total=total,
        shifts_with_violations=viol,
        average_score=Decimal("80.00"),
    )


def _location() -> LocationRow:
    return LocationRow(
        location_id=uuid.uuid4(),
        location_name="Main",
        shifts_total=10,
        shifts_with_violations=2,
        average_score=Decimal("85.00"),
    )


def _template() -> TemplateRow:
    return TemplateRow(
        template_id=uuid.uuid4(),
        template_name="Morning",
        shifts_total=8,
        shifts_with_violations=1,
        average_score=Decimal("90.00"),
    )


def _post(*, shifts_total: int = 5) -> PostRow:
    return PostRow(
        location_id=uuid.uuid4(),
        location_name="Main",
        slot_index=0,
        station_label="Terrace",
        shifts_total=shifts_total,
        shifts_with_violations=0,
        average_score=Decimal("88.00"),
    )


def _make_use_case(
    *,
    kpis: KpiBlock = _kpi(),
    heatmap: list[HeatmapCell] | None = None,
    violators: list[ViolatorRow] | None = None,
    locations: list[LocationRow] | None = None,
    templates: list[TemplateRow] | None = None,
    posts: list[PostRow] | None = None,
    criticality: list[CriticalityRow] | None = None,
    antifake: AntifakeBlock | None = None,
    sla: SlaBlock | None = None,
    role_split: RoleSplitBlock | None = None,
) -> AnalyticsOverviewUseCase:
    """Build a use case where every async query method is stubbed.

    We don't touch ``__init__`` (it accepts an AsyncSession) — instead we
    pass a sentinel session and immediately replace the methods that
    would query it. The use case's coordination logic (compare flow,
    density flags, range validation) is what we want to test, not the
    SQL.
    """
    use_case = AnalyticsOverviewUseCase(session=AsyncMock())
    use_case._kpis = AsyncMock(return_value=kpis)  # type: ignore[method-assign]
    use_case._heatmap = AsyncMock(return_value=heatmap or [])  # type: ignore[method-assign]
    use_case._top_violators = AsyncMock(  # type: ignore[method-assign]
        return_value=violators or []
    )
    use_case._locations = AsyncMock(return_value=locations or [])  # type: ignore[method-assign]
    use_case._templates = AsyncMock(return_value=templates or [])  # type: ignore[method-assign]
    use_case._posts = AsyncMock(return_value=posts or [])  # type: ignore[method-assign]
    use_case._criticality = AsyncMock(return_value=criticality or [])  # type: ignore[method-assign]
    use_case._antifake = AsyncMock(  # type: ignore[method-assign]
        return_value=antifake
        or AntifakeBlock(
            attachments_total=0, suspicious_total=0, suspicious_rate=None
        )
    )
    use_case._sla = AsyncMock(  # type: ignore[method-assign]
        return_value=sla
        or SlaBlock(
            threshold_min=15,
            shifts_with_actual=0,
            late_count=0,
            late_rate=None,
            avg_late_min=None,
        )
    )
    use_case._role_split = AsyncMock(  # type: ignore[method-assign]
        return_value=role_split
        or RoleSplitBlock(operator=_kpi(), bartender=_kpi()),
    )
    return use_case


# --- RBAC ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_non_admin_caller() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=7)
    result = await use_case.execute(
        user=_user(UserRole.OPERATOR),
        range_from=rf,
        range_to=rt,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "forbidden"


# --- Range validation ------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_range_when_to_before_from() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt + timedelta(days=1)  # 'from' is in the future of 'to'
    result = await use_case.execute(
        user=_user(),
        range_from=rf,
        range_to=rt,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "invalid_range"


@pytest.mark.asyncio
async def test_range_too_large_is_capped_to_max_days() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=MAX_DAYS + 1)
    result = await use_case.execute(
        user=_user(),
        range_from=rf,
        range_to=rt,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "range_too_large"


# --- Compare flow ----------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_returns_previous_with_same_length_and_no_nesting() -> None:
    use_case = _make_use_case(kpis=_kpi(total=10, clean=8, viol=2, avg=85))
    rt = datetime(2026, 4, 30, tzinfo=UTC)
    rf = rt - timedelta(days=7)
    result = await use_case.execute(
        user=_user(),
        range_from=rf,
        range_to=rt,
        compare=True,
    )
    assert isinstance(result, Success)
    dto = result.value
    assert dto.previous is not None
    assert dto.previous.previous is None  # no recursion
    # Length parity: previous window is exactly the same duration.
    assert (dto.previous.range_to - dto.previous.range_from) == (rt - rf)
    # Adjacency: previous window ends exactly where current starts.
    assert dto.previous.range_to == rf


@pytest.mark.asyncio
async def test_compare_disabled_means_no_previous_block() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=7)
    result = await use_case.execute(user=_user(), range_from=rf, range_to=rt)
    assert isinstance(result, Success)
    assert result.value.previous is None


# --- Violators limit -------------------------------------------------------


@pytest.mark.asyncio
async def test_violators_limit_is_propagated_to_query() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=30)
    await use_case.execute(
        user=_user(),
        range_from=rf,
        range_to=rt,
        violators_limit=5,
    )
    use_case._top_violators.assert_called_once()
    _, kwargs = use_case._top_violators.call_args
    assert kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_violators_limit_clamped_to_max() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=7)
    await use_case.execute(
        user=_user(),
        range_from=rf,
        range_to=rt,
        violators_limit=10_000,
    )
    _, kwargs = use_case._top_violators.call_args
    assert kwargs["limit"] <= 50  # MAX_VIOLATORS_LIMIT


# --- Density flags ---------------------------------------------------------


def test_density_kpis_empty_when_no_shifts() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=0),
        heatmap=[],
        violators=[],
        templates=[],
        posts=[],
    )
    assert d.kpis == "empty"


def test_density_kpis_low_when_below_threshold() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=3, clean=1),
        heatmap=[],
        violators=[],
        templates=[],
        posts=[],
    )
    assert d.kpis == "low"


def test_density_kpis_ok_when_threshold_met() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=5, clean=4),
        heatmap=[
            HeatmapCell(day_of_week=1, hour_of_day=10, shift_count=5, average_score=Decimal("80"))
        ],
        violators=[_violator(total=3) for _ in range(3)],
        templates=[_template(), _template()],
        posts=[_post(shifts_total=5), _post(shifts_total=5)],
    )
    assert d.kpis == "ok"


def test_density_heatmap_low_when_few_closed_shifts() -> None:
    cells = [
        HeatmapCell(day_of_week=1, hour_of_day=10, shift_count=1, average_score=Decimal("80"))
    ]
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=10, clean=8),
        heatmap=cells,
        violators=[],
        templates=[],
        posts=[],
    )
    assert d.heatmap == "low"


def test_density_heatmap_ok_when_enough_closed_shifts() -> None:
    cells = [
        HeatmapCell(day_of_week=1, hour_of_day=10, shift_count=20, average_score=Decimal("80"))
    ]
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=20, clean=15),
        heatmap=cells,
        violators=[],
        templates=[],
        posts=[],
    )
    assert d.heatmap == "ok"


def test_density_violators_low_when_few_qualified() -> None:
    # Two violators have enough shifts (≥3) and one doesn't — threshold
    # is 3 qualified rows.
    qualified = [_violator(total=5) for _ in range(2)]
    unqualified = replace(_violator(total=1), shifts_total=1)
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=20, clean=10),
        heatmap=[],
        violators=[*qualified, unqualified],
        templates=[],
        posts=[],
    )
    assert d.violators == "low"


def test_density_templates_low_when_only_one_template() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=10, clean=10),
        heatmap=[],
        violators=[],
        templates=[_template()],
        posts=[],
    )
    assert d.templates == "low"


def test_density_posts_empty_when_no_rows() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=10, clean=10),
        heatmap=[],
        violators=[],
        templates=[_template(), _template()],
        posts=[],
    )
    assert d.posts == "empty"


def test_density_posts_low_when_few_rows_or_low_median() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=10, clean=10),
        heatmap=[],
        violators=[],
        templates=[_template(), _template()],
        posts=[_post(shifts_total=2)],
    )
    assert d.posts == "low"

    d2 = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=10, clean=10),
        heatmap=[],
        violators=[],
        templates=[_template(), _template()],
        posts=[_post(shifts_total=2), _post(shifts_total=2)],
    )
    assert d2.posts == "low"


def test_density_posts_ok_when_enough_rows_and_median() -> None:
    d = AnalyticsOverviewUseCase._density(
        kpis=_kpi(total=30, clean=30),
        heatmap=[],
        violators=[],
        templates=[_template(), _template()],
        posts=[
            _post(shifts_total=5),
            _post(shifts_total=5),
            replace(_post(shifts_total=5), slot_index=1, station_label="Hall"),
        ],
    )
    assert d.posts == "ok"


# --- SLA / role-split / serialisation hooks -------------------------------


@pytest.mark.asyncio
async def test_role_split_falls_back_to_empty_kpi_when_role_missing() -> None:
    """Role-split is supposed to be empty-safe — if no bartender shifted in
    the window, the API still returns a well-formed empty KPI block. The
    serialiser at the boundary will then marshal it as zeros, not nulls.
    """
    role_split = RoleSplitBlock(
        operator=_kpi(total=10, clean=8, viol=2, avg=85),
        bartender=_kpi(),  # nothing here
    )
    use_case = _make_use_case(role_split=role_split)
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=30)
    result = await use_case.execute(user=_user(), range_from=rf, range_to=rt)
    assert isinstance(result, Success)
    rs = result.value.role_split
    assert rs is not None
    assert rs.bartender.shifts_closed == 0
    assert rs.operator.shifts_closed == 10


@pytest.mark.asyncio
async def test_sla_block_passes_through_threshold_and_rates() -> None:
    sla = SlaBlock(
        threshold_min=15,
        shifts_with_actual=10,
        late_count=2,
        late_rate=Decimal("0.20"),
        avg_late_min=Decimal("23.4"),
    )
    use_case = _make_use_case(sla=sla)
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=7)
    result = await use_case.execute(user=_user(), range_from=rf, range_to=rt)
    assert isinstance(result, Success)
    out = result.value.sla_late_start
    assert out is not None
    assert out.late_rate == Decimal("0.20")
    assert out.late_count == 2


@pytest.mark.asyncio
async def test_default_violators_limit_is_used_when_unspecified() -> None:
    use_case = _make_use_case()
    rt = datetime.now(tz=UTC)
    rf = rt - timedelta(days=30)
    await use_case.execute(user=_user(), range_from=rf, range_to=rt)
    _, kwargs = use_case._top_violators.call_args
    assert kwargs["limit"] == DEFAULT_VIOLATORS_LIMIT
