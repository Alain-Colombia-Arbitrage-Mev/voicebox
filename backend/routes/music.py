"""Background music generation endpoints (MiniMax music API)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import VoiceProfile as DBVoiceProfile, get_db
from ..services import history
from ..services.music import MUSIC_PROFILE_NAME, run_music_generation
from ..services.task_queue import enqueue_generation
from ..utils.tasks import get_task_manager

router = APIRouter()


def _get_or_create_music_profile(db: Session) -> DBVoiceProfile:
    """Singleton profile music generations hang off — mirrors the
    "Imported Audio" profile so story/history plumbing works unchanged."""
    row = (
        db.query(DBVoiceProfile)
        .filter(DBVoiceProfile.name == MUSIC_PROFILE_NAME)
        .first()
    )
    if row is not None:
        return row
    row = DBVoiceProfile(
        id=str(uuid.uuid4()),
        name=MUSIC_PROFILE_NAME,
        description="AI-generated background music for the story timeline.",
        language="en",
        voice_type="import",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/music/generate", response_model=models.GenerationResponse)
async def generate_music(
    data: models.MusicGenerationRequest,
    db: Session = Depends(get_db),
):
    """Generate background music from a style prompt.

    The result is registered as a generation row (profile "Meditation
    Music") so it can be played, exported, and arranged on the story
    timeline alongside voice generations.
    """
    from ..services.settings import get_minimax_settings

    if not get_minimax_settings(db).api_key:
        raise HTTPException(
            status_code=400,
            detail="MiniMax API key not configured. Add it in Settings → MiniMax.",
        )

    profile = _get_or_create_music_profile(db)
    generation_id = str(uuid.uuid4())

    generation = await history.create_generation(
        profile_id=profile.id,
        text=data.prompt,
        language="en",
        audio_path="",
        duration=0,
        seed=None,
        db=db,
        generation_id=generation_id,
        status="generating",
        engine="minimax",
        source="music",
    )

    get_task_manager().start_generation(
        task_id=generation_id,
        profile_id=profile.id,
        text=data.prompt,
    )

    enqueue_generation(
        generation_id,
        run_music_generation(
            generation_id=generation_id,
            prompt=data.prompt,
            lyrics=data.lyrics,
            instrumental=data.instrumental,
            model=data.model,
        ),
    )

    return generation
