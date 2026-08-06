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

    # Hybrid mode: MiniMax composes the ambient bed, the exact tone gets
    # infused underneath (an AI music model can't emit precise Hz itself).
    if data.with_music:
        from ..services.music import run_frequency_music_generation
        from ..services.settings import get_minimax_settings
        from ..services.task_queue import enqueue_generation
        from ..utils.tasks import get_task_manager

        if not get_minimax_settings(db).api_key:
            raise HTTPException(
                status_code=400,
                detail="MiniMax API key not configured. Add it in Settings → MiniMax.",
            )

        music_prompt = data.music_prompt or (
            f"calm ambient meditation music, soft ethereal pads, very slow, peaceful, "
            f"healing {carrier:g}hz atmosphere, no drums, no melody spikes"
        )
        profile = _get_or_create_frequencies_profile(db)
        generation_id = str(uuid.uuid4())
        generation = await history.create_generation(
            profile_id=profile.id,
            text=f"{label} + música",
            language="en",
            audio_path="",
            duration=0,
            seed=None,
            db=db,
            generation_id=generation_id,
            status="generating",
            engine="minimax",
            source="frequency",
        )
        get_task_manager().start_generation(
            task_id=generation_id, profile_id=profile.id, text=label
        )
        enqueue_generation(
            generation_id,
            run_frequency_music_generation(
                generation_id=generation_id,
                music_prompt=music_prompt,
                carrier_hz=carrier,
                beat_hz=beat,
                mode=mode,
                duration_sec=data.duration_sec,
                tone_volume=data.volume,
            ),
        )
        return generation

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
