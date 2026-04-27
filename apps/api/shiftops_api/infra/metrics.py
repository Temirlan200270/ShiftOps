"""Prometheus business metrics — single source of truth.

Why one module
--------------
Every business metric this service exposes is defined here so we can:

1. Audit cardinality at a glance (one file = one place to look for label
   explosions).
2. Keep the names stable across releases — the Grafana dashboards in
   ``ops/grafana/`` reference these strings.
3. Avoid the classic Prometheus footgun of redefining the same metric
   in two import paths and crashing on duplicate-registration.

Naming convention
-----------------
All custom metrics use the ``shiftops_`` prefix, both because we share
a Grafana Cloud workspace with other services and because dashboards
are cleaner when you can filter `shiftops_*` in autocomplete.

HTTP-level metrics (latency, QPS, in-progress) are NOT in this file —
they're emitted by ``prometheus_fastapi_instrumentator`` configured in
``shiftops_api.main``. The Instrumentator gives us:

- ``shiftops_api_latency_seconds`` — histogram (overridden name).
- ``http_requests_total`` — counter (default name kept).
- ``http_requests_inprogress`` — gauge (default name kept).

Cardinality budget
------------------
We assume the pilot scale: ≤10 organisations, ≤30 locations each, ≤30
tasks per shift template. With that ceiling, ``location_id`` and
``template_id`` are safe as labels (a few hundred series). If we ever
multi-tenant past that, we move location-scoped series to a
recording-rule rollup.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Shift lifecycle
# ---------------------------------------------------------------------------

SHIFTS_STARTED_TOTAL = Counter(
    "shiftops_shifts_started_total",
    "Shifts moved from scheduled → active.",
    labelnames=("location_id", "template_id"),
)

SHIFTS_CLOSED_TOTAL = Counter(
    "shiftops_shifts_closed_total",
    "Shifts moved to a terminal status.",
    labelnames=("location_id", "status"),
)

# ---------------------------------------------------------------------------
# Tasks & violations
# ---------------------------------------------------------------------------

TASKS_COMPLETED_TOTAL = Counter(
    "shiftops_tasks_completed_total",
    "Task instances that reached `done` (excludes waivers).",
    labelnames=("criticality",),
)

# `type` enumerates concrete rule breaks; keep this set tight to avoid
# label-cardinality drift. New violation types should land here as
# explicit constants.
VIOLATION_TYPE_INCOMPLETE_REQUIRED = "incomplete_required"
VIOLATION_TYPE_LATE_CLOSE = "late_close"
VIOLATION_TYPE_PHASH_COLLISION = "phash_collision"

VIOLATIONS_TOTAL = Counter(
    "shiftops_violations_total",
    "Discrete rule violations recorded at shift close (or photo capture for phash).",
    labelnames=("type", "location_id"),
)

ATTACHMENT_PHASH_COLLISIONS_TOTAL = Counter(
    "shiftops_attachment_phash_collisions_total",
    "Photos that perceptually matched a recent attachment (anti-fake check).",
)

ATTACHMENTS_UPLOADED_TOTAL = Counter(
    "shiftops_attachments_uploaded_total",
    "Photos persisted via the StorageProvider.",
    labelnames=("provider", "suspicious"),
)

# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------

# Funnel: every waiver starts as `open` and resolves to `approved` or
# `rejected`. Keeping all three statuses on one Counter (instead of
# two separate ones) means dashboards can compute approval-rate via a
# single `rate()` ratio.
WAIVER_STATUS_OPEN = "open"
WAIVER_STATUS_APPROVED = "approved"
WAIVER_STATUS_REJECTED = "rejected"

WAIVER_REQUESTS_TOTAL = Counter(
    "shiftops_waiver_requests_total",
    "Waiver requests by lifecycle status (open → approved | rejected).",
    labelnames=("status",),
)

WAIVER_DECISIONS_TOTAL = Counter(
    "shiftops_waiver_decisions_total",
    "Waiver decisions recorded by admins. Same data as `_requests_total{status!=open}` but kept separate for legacy dashboards.",
    labelnames=("decision",),
)

# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

TELEGRAM_SEND_TOTAL = Counter(
    "shiftops_telegram_send_total",
    "Outbound Telegram requests.",
    labelnames=("method", "result"),
)

TELEGRAM_SEND_DURATION_SECONDS = Histogram(
    "shiftops_telegram_send_duration_seconds",
    "End-to-end duration of a Telegram API call (queue + network + retry).",
    labelnames=("method",),
    # Telegram p95 is ~300 ms in normal weather, hits seconds on 429.
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# ---------------------------------------------------------------------------
# Realtime / CSV import
# ---------------------------------------------------------------------------

REALTIME_WS_CONNECTIONS = Gauge(
    "shiftops_realtime_ws_connections",
    "Open live-monitor WebSocket sessions.",
)

CSV_IMPORT_ROWS_TOTAL = Counter(
    "shiftops_csv_import_rows_total",
    "Rows processed by the CSV schedule importer.",
    labelnames=("outcome",),  # created | skipped | error | dry_run
)


__all__ = [
    "ATTACHMENT_PHASH_COLLISIONS_TOTAL",
    "ATTACHMENTS_UPLOADED_TOTAL",
    "CSV_IMPORT_ROWS_TOTAL",
    "REALTIME_WS_CONNECTIONS",
    "SHIFTS_CLOSED_TOTAL",
    "SHIFTS_STARTED_TOTAL",
    "TASKS_COMPLETED_TOTAL",
    "TELEGRAM_SEND_DURATION_SECONDS",
    "TELEGRAM_SEND_TOTAL",
    "VIOLATIONS_TOTAL",
    "VIOLATION_TYPE_INCOMPLETE_REQUIRED",
    "VIOLATION_TYPE_LATE_CLOSE",
    "VIOLATION_TYPE_PHASH_COLLISION",
    "WAIVER_DECISIONS_TOTAL",
    "WAIVER_REQUESTS_TOTAL",
    "WAIVER_STATUS_APPROVED",
    "WAIVER_STATUS_OPEN",
    "WAIVER_STATUS_REJECTED",
]
