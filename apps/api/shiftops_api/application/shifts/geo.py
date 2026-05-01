"""Geolocation helpers for optional shift-start checks (TWA → API)."""

from __future__ import annotations

import math
from typing import Any

_NUM = (int, float)


def extract_geo_point(geo: dict[str, Any] | None) -> tuple[float, float] | None:
    """Read ``lat``/``lng`` (or ``latitude``/``longitude``) from ``locations.geo`` JSON."""

    if not geo:
        return None
    lat = geo.get("lat", geo.get("latitude"))
    lng = geo.get("lng", geo.get("longitude"))
    if lat is None or lng is None:
        return None
    if not isinstance(lat, _NUM) or not isinstance(lng, _NUM):
        return None
    return float(lat), float(lng)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (WGS84 sphere approximation)."""

    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    h = math.sin(d_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))
