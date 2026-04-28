"""CORS policy regression tests.

Browser `fetch()` failures with "Failed to fetch" often mean the preflight
`OPTIONS` never received permissive `Access-Control-*` headers. These tests
lock the behaviour expected by the Next.js app on Vercel and Telegram WebView.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shiftops_api.config import get_settings
from shiftops_api.main import apply_cors_middleware


@pytest.fixture
def cors_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        "http://localhost:3000,https://shiftops-web.vercel.app",
    )
    get_settings.cache_clear()

    app = FastAPI()
    apply_cors_middleware(app, get_settings())

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"ok": "1"}

    return TestClient(app)


def test_preflight_allows_vercel_preview_origin(cors_client: TestClient) -> None:
    origin = "https://shiftops-git-feature-xyz.vercel.app"
    r = cors_client.options(
        "/probe",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_preflight_allows_explicit_dashboard_origin(cors_client: TestClient) -> None:
    origin = "https://shiftops-web.vercel.app"
    r = cors_client.options(
        "/probe",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_preflight_allows_telegram_embed_origin(cors_client: TestClient) -> None:
    origin = "https://web.telegram.org"
    r = cors_client.options(
        "/probe",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_preflight_allows_private_network_header(cors_client: TestClient) -> None:
    """Chrome may send this on preflight; middleware must not 400."""
    origin = "https://shiftops-web.vercel.app"
    r = cors_client.options(
        "/probe",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_preflight_rejects_unknown_origin(cors_client: TestClient) -> None:
    r = cors_client.options(
        "/probe",
        headers={
            "Origin": "https://malicious.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 400


def test_simple_get_reflects_allowed_origin(cors_client: TestClient) -> None:
    origin = "http://localhost:3000"
    r = cors_client.get("/probe", headers={"Origin": origin})
    assert r.status_code == 200
    assert r.json() == {"ok": "1"}
    assert r.headers.get("access-control-allow-origin") == origin
