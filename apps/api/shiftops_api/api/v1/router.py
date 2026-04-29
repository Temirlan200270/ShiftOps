"""V1 router aggregator.

Each domain area lives in its own module and gets included here.
"""

from __future__ import annotations

from fastapi import APIRouter

from shiftops_api.api.v1 import (
    analytics,
    auth,
    invites,
    locations,
    media,
    organization,
    realtime,
    schedule,
    shifts,
    team,
    telegram,
    templates,
)

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(invites.router, prefix="/invites", tags=["invites"])
api_v1_router.include_router(locations.router, prefix="/locations", tags=["locations"])
api_v1_router.include_router(
    organization.router, prefix="/organization", tags=["organization"]
)
api_v1_router.include_router(team.router, prefix="/team", tags=["team"])
api_v1_router.include_router(shifts.router, prefix="/shifts", tags=["shifts"])
api_v1_router.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
api_v1_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_v1_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_v1_router.include_router(realtime.router, prefix="/realtime", tags=["realtime"])
api_v1_router.include_router(media.router, prefix="/media", tags=["media"])
api_v1_router.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
