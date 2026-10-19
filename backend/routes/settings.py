"""User settings endpoints — capture/refine and generation defaults."""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/captures", response_model=models.CaptureSettingsResponse)
async def get_capture_settings_endpoint(db: Session = Depends(get_db)):
    return settings_service.get_capture_settings(db)


@router.put("/captures", response_model=models.CaptureSettingsResponse)
async def update_capture_settings_endpoint(
    patch: models.CaptureSettingsUpdate,
    db: Session = Depends(get_db),
):
    return settings_service.update_capture_settings(db, patch.model_dump(exclude_unset=True))


@router.get("/generation", response_model=models.GenerationSettingsResponse)
async def get_generation_settings_endpoint(db: Session = Depends(get_db)):
    return settings_service.get_generation_settings(db)


@router.put("/generation", response_model=models.GenerationSettingsResponse)
async def update_generation_settings_endpoint(
    patch: models.GenerationSettingsUpdate,
    db: Session = Depends(get_db),
):
    return settings_service.update_generation_settings(db, patch.model_dump(exclude_unset=True))


def _minimax_response(row) -> models.MiniMaxSettingsResponse:
    """Never echo the full API key back to clients — expose set/preview only."""
    key = row.api_key or os.environ.get("MINIMAX_API_KEY") or ""
    return models.MiniMaxSettingsResponse(
        api_key_set=bool(key),
        api_key_preview=key[-4:] if key else None,
        group_id=row.group_id,
        api_host=row.api_host,
        model=row.model,
    )


@router.get("/minimax", response_model=models.MiniMaxSettingsResponse)
async def get_minimax_settings_endpoint(db: Session = Depends(get_db)):
    return _minimax_response(settings_service.get_minimax_settings(db))


@router.put("/minimax", response_model=models.MiniMaxSettingsResponse)
async def update_minimax_settings_endpoint(
    patch: models.MiniMaxSettingsUpdate,
    db: Session = Depends(get_db),
):
    row = settings_service.update_minimax_settings(db, patch.model_dump(exclude_unset=True))
    return _minimax_response(row)


def _fish_response(row):
    return models.FishSettingsResponse(
        api_key_set=bool(row.api_key or os.environ.get("FISH_AUDIO_API_KEY")), model=row.model,
    )


@router.get("/fish", response_model=models.FishSettingsResponse)
async def get_fish_settings_endpoint(db: Session = Depends(get_db)):
    return _fish_response(settings_service.get_fish_settings(db))


@router.put("/fish", response_model=models.FishSettingsResponse)
async def update_fish_settings_endpoint(patch: models.FishSettingsUpdate, db: Session = Depends(get_db)):
    return _fish_response(settings_service.update_fish_settings(db, patch.model_dump(exclude_unset=True)))
