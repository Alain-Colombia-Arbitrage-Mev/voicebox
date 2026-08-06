"""Healing-frequency / brainwave tone generation endpoints.

Local numpy synthesis — instant and offline, no API credits involved.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config, models
from ..database import VoiceProfile as DBVoiceProfile, get_db
from ..services import history
from ..services.frequencies import (
    FREQUENCY_PRESETS,
    FREQUENCY_SAMPLE_RATE,
    get_preset,
    synthesize,
)

router = APIRouter()

FREQUENCIES_PROFILE_NAME = "Frequencies"


def _get_or_create_frequencies_profile(db: Session) -> DBVoiceProfile:
    """Singleton profile frequency clips hang off — same pattern as the
    imported-audio and music profiles, keeps story/history plumbing intact."""
    row = (
        db.query(DBVoiceProfile)
        .filter(DBVoiceProfile.name == FREQUENCIES_PROFILE_NAME)
        .first()
    )
    if row is not None:
        return row
    row = DBVoiceProfile(
        id=str(uuid.uuid4()),
        name=FREQUENCIES_PROFILE_NAME,
        description="Healing frequencies and brainwave entrainment tones.",
        language="en",
        voice_type="import",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/frequencies/presets")
async def list_frequency_presets():
    """List available frequency presets with their descriptions."""
    return {
        "presets": [
            {
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "carrier_hz": p.carrier_hz,
                "beat_hz": p.beat_hz,
                "mode": p.mode,
                "tags": p.tags,
            }
            for p in FREQUENCY_PRESETS
        ]
    }


@router.post("/frequencies/generate", response_model=models.GenerationResponse)
async def generate_frequency(
    data: models.FrequencyGenerationRequest,
    db: Session = Depends(get_db),
):
    """Synthesize a frequency/entrainment tone and register it as a
    generation so it can be arranged on the story timeline.

    Synthesis is local and fast, so this endpoint is synchronous and
    returns the completed row directly.
    """
    if data.preset:
        preset = get_preset(data.preset)
        if preset is None:
            raise HTTPException(status_code=400, detail=f"Unknown preset: {data.preset}")
        carrier = preset.carrier_hz
        beat = data.beat_hz if data.beat_hz is not None else preset.beat_hz
        mode = data.mode or preset.mode
        label = preset.name
    else:
        if data.carrier_hz is None:
            raise HTTPException(status_code=400, detail="Provide either preset or carrier_hz")
        carrier = data.carrier_hz
        beat = data.beat_hz or 0.0
        mode = data.mode or ("binaural" if beat > 0 else "pure")
        label = f"{carrier:g} Hz" + (f" + {beat:g} Hz {mode}" if beat > 0 else " tono puro")

    # Binaural collapses to a plain beat in mono playback contexts; the
    # user can force isochronic for speaker-friendly output.
    audio = await asyncio.to_thread(
        synthesize,
        carrier_hz=carrier,
        beat_hz=beat,
        mode=mode,
        duration_sec=data.duration_sec,
        volume=data.volume,
    )

    from ..utils.audio import save_audio

    generation_id = str(uuid.uuid4())
    target = config.get_generations_dir() / f"{generation_id}.wav"
    await asyncio.to_thread(save_audio, audio, str(target), FREQUENCY_SAMPLE_RATE)

    duration = float(audio.shape[0]) / FREQUENCY_SAMPLE_RATE
    profile = _get_or_create_frequencies_profile(db)

    return await history.create_generation(
        profile_id=profile.id,
        text=label,
        language="en",
        audio_path=config.to_storage_path(target),
        duration=duration,
        seed=None,
        db=db,
        generation_id=generation_id,
        status="completed",
        engine=None,
        source="frequency",
    )
