"""Pilot smoke harness — exercises the full operator flow against a running API.

Usage::

    docker compose exec api python scripts/smoke_pilot.py

Why a Python script and not a Playwright TWA test?

- The TWA UI test requires a real Telegram client (initData is only issued by
  Telegram). We exercise the API with a synthetic, signed initData generated
  by the same `InitDataValidator.build_init_data` helper that our unit tests
  use — so the back-end signature check is the same code path as production.
- This script complements the manual TWA checklist in docs/PILOT_SMOKE.md.

It expects:

- The seeded morning shift (from `scripts/seed.py`) to exist for today.
- `TG_BOT_TOKEN` to be set; we sign the synthetic initData with it.
- The operator's TelegramAccount row (seeded with tg_user_id=-3) to be
  re-mapped to the synthetic id we sign here. The script does that mapping
  directly via SQL (privileged session, not exposed to the API).

Exit code: 0 on full pass, non-zero on the first failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
from sqlalchemy import text

from shiftops_api.config import get_settings
from shiftops_api.infra.db.engine import get_engine, get_sessionmaker
from shiftops_api.infra.telegram.init_data import InitDataValidator


SYNTHETIC_TG_USER_ID = 9_999_001
SEED_OPERATOR_USER_ID = "33333333-3333-3333-3333-333333333333"


def _build_init_data(bot_token: str) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAAaa",
        "user": json.dumps(
            {
                "id": SYNTHETIC_TG_USER_ID,
                "first_name": "Smoke",
                "last_name": "Operator",
                "username": "smoke_op",
                "language_code": "ru",
            },
            separators=(",", ":"),
        ),
    }
    return InitDataValidator.build_init_data(bot_token, payload)


async def _link_synthetic_account_to_seed_operator() -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO telegram_accounts (tg_user_id, user_id, tg_username, tg_language_code)
                VALUES (:tg_id, :uid, :uname, 'ru')
                ON CONFLICT (tg_user_id) DO UPDATE
                  SET user_id = EXCLUDED.user_id
                """
            ),
            {"tg_id": SYNTHETIC_TG_USER_ID, "uid": SEED_OPERATOR_USER_ID, "uname": "smoke_op"},
        )
        await session.commit()


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


async def _run() -> int:
    settings = get_settings()
    api_base = os.environ.get("SMOKE_API_URL", settings.api_public_url).rstrip("/")
    bot_token = settings.tg_bot_token.get_secret_value()
    if not bot_token:
        print("FAIL: TG_BOT_TOKEN is empty", file=sys.stderr)
        return 2

    await _link_synthetic_account_to_seed_operator()

    init_data = _build_init_data(bot_token)
    async with httpx.AsyncClient(base_url=api_base, timeout=30.0) as client:
        print(f"[1/5] handshake → POST /v1/auth/exchange ({api_base})")
        resp = await client.post("/v1/auth/exchange", json={"init_data": init_data})
        if resp.status_code != 200:
            print("FAIL handshake:", resp.status_code, resp.text)
            return 3
        access_token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {access_token}"

        print("[2/5] my-shift → GET /v1/shifts/me")
        resp = await client.get("/v1/shifts/me")
        if resp.status_code == 404:
            print("FAIL: no scheduled shift today — run scripts/seed.py first")
            return 5
        if resp.status_code != 200:
            print("FAIL get my shift:", resp.status_code, resp.text)
            return 4
        body = resp.json()
        shift_id = body["shift"]["id"]
        tasks = body["tasks"]
        print(f"  shift={shift_id}  tasks={len(tasks)}")

        print(f"[3/5] start shift → POST /v1/shifts/{shift_id}/start")
        resp = await client.post(f"/v1/shifts/{shift_id}/start")
        if resp.status_code != 200:
            print("FAIL start:", resp.status_code, resp.text)
            return 6

        print("[4/5] complete tasks (skipping critical+photo without photo blob)")
        # We don't have a real camera here. In a real smoke we'd attach a
        # small JPEG; locally we substitute a minimal valid JPEG so the
        # photo-required path executes end-to-end.
        tiny_jpeg = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000806060707"
            "06080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20"
            "242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ff"
            "c0000b0800010001010122003ffd9"
        )

        for t in tasks:
            tid = t["id"]
            files = {}
            data: dict[str, str] = {}
            if t["requires_photo"]:
                files["photo"] = ("smoke.jpg", tiny_jpeg, "image/jpeg")
            if t["requires_comment"]:
                data["comment"] = "smoke OK"
            resp = await client.post(
                f"/v1/shifts/tasks/{tid}/complete", data=data, files=files
            )
            if resp.status_code != 200:
                print(f"FAIL complete {tid}:", resp.status_code, resp.text)
                return 7

        print(f"[5/5] close shift → POST /v1/shifts/{shift_id}/close")
        resp = await client.post(
            f"/v1/shifts/{shift_id}/close",
            params={"confirm_violations": "false"},
        )
        if resp.status_code != 200:
            print("FAIL close:", resp.status_code, resp.text)
            return 8
        closed = resp.json()
        print("  closed:", _pretty(closed))

        if closed.get("final_status") not in ("closed_clean", "closed_with_violations"):
            print("FAIL: unexpected final status:", closed)
            return 9
        score = float(closed.get("score") or 0)
        if score < 50:
            print(f"FAIL: suspiciously low score {score}")
            return 10

    print("\nSMOKE OK ✅")
    return 0


async def main() -> int:
    """Wrapper that guarantees the SQLAlchemy engine is disposed even on early
    failures — leaking it stalls pytest / CI shutdown for the asyncpg pool's
    grace period (5 s)."""
    try:
        return await _run()
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
