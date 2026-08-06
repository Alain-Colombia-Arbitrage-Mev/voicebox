"""Voice profile endpoints."""

import io
import json as _json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .. import config, models
from ..app import safe_content_disposition
from ..database import VoiceProfile as DBVoiceProfile, get_db
from ..services import channels, export_import, personality, profiles
from ..services.profiles import _profile_to_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/profiles", response_model=models.VoiceProfileResponse)
async def create_profile(
    data: models.VoiceProfileCreate,
    db: Session = Depends(get_db),
):
    """Create a new voice profile."""
    try:
        return await profiles.create_profile(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/profiles", response_model=list[models.VoiceProfileResponse])
async def list_profiles(db: Session = Depends(get_db)):
    """List all voice profiles."""
    return await profiles.list_profiles(db)


@router.post("/profiles/import", response_model=models.VoiceProfileResponse)
async def import_profile(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a voice profile from a ZIP archive."""
    MAX_FILE_SIZE = 100 * 1024 * 1024

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400, detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB"
        )

    try:
        profile = await export_import.import_profile_from_zip(content, db)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Preset Voice Endpoints ───────────────────────────────────────────
# These MUST be declared before /profiles/{profile_id} to avoid the
# wildcard swallowing "presets" as a profile_id.


@router.get("/profiles/presets/{engine}")
async def list_preset_voices(engine: str):
    """List available preset voices for an engine."""
    if engine == "kokoro":
        from ..backends.kokoro_backend import KOKORO_VOICES

        return {
            "engine": engine,
            "voices": [
                {
                    "voice_id": vid,
                    "name": name,
                    "gender": gender,
                    "language": lang,
                }
                for vid, name, gender, lang in KOKORO_VOICES
            ],
        }
    if engine == "qwen_custom_voice":
        from ..backends.qwen_custom_voice_backend import QWEN_CUSTOM_VOICES

        return {
            "engine": engine,
            "voices": [
                {
                    "voice_id": speaker_id,
                    "name": display_name,
                    "gender": gender,
                    "language": lang,
                }
                for speaker_id, display_name, gender, lang, _desc in QWEN_CUSTOM_VOICES
            ],
        }
    if engine == "minimax":
        from ..backends.minimax_backend import MINIMAX_VOICES

        return {
            "engine": engine,
            "voices": [
                {
                    "voice_id": vid,
                    "name": name,
                    "gender": gender,
                    "language": lang,
                }
                for vid, name, gender, lang in MINIMAX_VOICES
            ],
        }
    return {"engine": engine, "voices": []}

@router.get("/profiles/{profile_id}", response_model=models.VoiceProfileResponse)
async def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get a voice profile by ID."""
    profile = await profiles.get_profile(profile_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/profiles/{profile_id}/copy-prosody", response_model=models.VoiceProfileResponse)
async def copy_profile_prosody(
    profile_id: str,
    data: models.CopyProsodyRequest,
    db: Session = Depends(get_db),
):
    """Copy delivery settings (emotion/speed/pitch, optionally effects and
    personality) from another profile onto this one. Applies to future
    generations with this profile."""
    target = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found")
    source = db.query(DBVoiceProfile).filter_by(id=data.source_profile_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source profile not found")

    target.default_emotion = source.default_emotion
    target.default_speed = source.default_speed
    target.default_pitch = source.default_pitch
    if data.include_effects:
        target.effects_chain = source.effects_chain
    if data.include_personality:
        target.personality = source.personality
    db.commit()
    db.refresh(target)
    return _profile_to_response(target)


@router.post("/profiles/{profile_id}/analyze-prosody", response_model=models.ProsodyAnalysisResponse)
async def analyze_profile_prosody(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Capture delivery prosody (speed, emotion) from the profile's
    reference audio and store it as the profile's generation defaults."""
    import asyncio

    from ..database import ProfileSample as DBProfileSample
    from ..services import prosody as prosody_service

    profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    sample = db.query(DBProfileSample).filter_by(profile_id=profile_id).first()
    if not sample:
        raise HTTPException(status_code=400, detail="Profile has no reference samples to analyze")

    audio_path = config.resolve_storage_path(sample.audio_path)
    if audio_path is None or not audio_path.exists():
        raise HTTPException(status_code=404, detail="Sample audio file not found")

    try:
        analysis = await asyncio.to_thread(
            prosody_service.analyze_sample, str(audio_path), sample.reference_text
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prosody analysis failed: {e}")

    # Cloned voices already reproduce the reference pacing at speed 1.0 —
    # storing the captured multiplier would double-apply it. Only preset
    # voices (which have their own neutral pace) get the speed default.
    voice_type = getattr(profile, "voice_type", None) or "cloned"
    stored_speed = None if voice_type == "cloned" else analysis.speed

    profile.default_emotion = analysis.emotion
    profile.default_speed = stored_speed
    profile.default_pitch = analysis.pitch

    # Reproduce the sample's production character (room reverb / echo) as
    # the profile's default effects chain. Never clobber a chain the user
    # configured by hand.
    if analysis.effects_chain and not profile.effects_chain:
        profile.effects_chain = _json.dumps(analysis.effects_chain)
    db.commit()

    return models.ProsodyAnalysisResponse(
        profile_id=profile_id,
        default_emotion=analysis.emotion,
        default_speed=stored_speed,
        default_pitch=analysis.pitch,
        syllables_per_sec=analysis.syllables_per_sec,
        f0_median_hz=analysis.f0_median_hz,
        f0_std_semitones=analysis.f0_std_semitones,
        energy_cv=analysis.energy_cv,
        voiced_duration_sec=analysis.voiced_duration_sec,
        reverb_tail_sec=analysis.reverb_tail_sec,
        effects_chain=[models.EffectConfig(**e) for e in (analysis.effects_chain or [])],
    )


@router.put("/profiles/{profile_id}", response_model=models.VoiceProfileResponse)
async def update_profile(
    profile_id: str,
    data: models.VoiceProfileCreate,
    db: Session = Depends(get_db),
):
    """Update a voice profile."""
    try:
        profile = await profiles.update_profile(profile_id, data, db)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Delete a voice profile."""
    success = await profiles.delete_profile(profile_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"message": "Profile deleted successfully"}


SAMPLE_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
SAMPLE_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB


@router.post("/profiles/{profile_id}/samples", response_model=models.ProfileSampleResponse)
async def add_profile_sample(
    profile_id: str,
    file: UploadFile = File(...),
    reference_text: str = Form(...),
    db: Session = Depends(get_db),
):
    """Add a sample to a voice profile."""
    _allowed_audio_exts = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}
    _uploaded_ext = Path(file.filename or "").suffix.lower()
    file_suffix = _uploaded_ext if _uploaded_ext in _allowed_audio_exts else ".wav"

    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        total_size = 0
        while chunk := await file.read(SAMPLE_UPLOAD_CHUNK_SIZE):
            total_size += len(chunk)
            if total_size > SAMPLE_MAX_FILE_SIZE:
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (max {SAMPLE_MAX_FILE_SIZE // (1024 * 1024)} MB)",
                )
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        # Users routinely type a *description* ("male, calm, echo voice")
        # where the engine needs the *transcript* — which cripples clone
        # delivery fidelity and prosody capture. When the provided text is
        # clearly not a transcript (too short for the audio's speech
        # content), transcribe the sample with the local Whisper model.
        resolved_text = await _resolve_reference_text(tmp_path, reference_text)

        sample = await profiles.add_profile_sample(
            profile_id,
            tmp_path,
            resolved_text,
            db,
        )

        # Capture delivery prosody automatically so cloned profiles pick up
        # emotion/effects defaults without a manual analyze call. Best-effort.
        try:
            await _auto_capture_prosody(profile_id, db)
        except Exception:
            logger.debug("Auto prosody capture failed", exc_info=True)

        return sample
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process audio file: {str(e)}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def _resolve_reference_text(audio_path: str, provided_text: str) -> str:
    """Return the transcript for a sample, auto-transcribing when the
    user-provided text is clearly a description rather than a transcript.

    Heuristic: natural speech runs ~10-18 chars/second; text much shorter
    than the audio implies (under ~4 chars/s of file duration) can't be a
    transcript. Only replaces text when Whisper is already downloaded and
    produces something substantial; otherwise the provided text stands.
    """
    import asyncio

    provided = (provided_text or "").strip()
    try:
        import soundfile as sf

        duration = sf.info(audio_path).duration
    except Exception:
        return provided

    if duration <= 0 or len(provided) >= duration * 4:
        return provided  # plausibly a transcript — keep the user's text

    try:
        from ..services.transcribe import get_whisper_model

        whisper = get_whisper_model()
        checker = getattr(whisper, "_is_model_cached", None)
        whisper_size = getattr(whisper, "model_size", None) or "base"
        if checker is not None and not checker(whisper_size):
            return provided

        transcript = (await whisper.transcribe(audio_path) or "").strip()
        if len(transcript) > max(20, len(provided)):
            logger.info("Sample text looked like a description — using Whisper transcript")
            return transcript[:990]
    except Exception:
        logger.debug("Auto-transcription failed; keeping provided text", exc_info=True)
    return provided


async def _auto_capture_prosody(profile_id: str, db: Session) -> None:
    """Run prosody/effects capture for cloned profiles after a sample upload."""
    import asyncio

    from ..database import ProfileSample as DBProfileSample
    from ..services import prosody as prosody_service

    profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not profile or (profile.voice_type or "cloned") != "cloned":
        return
    sample = db.query(DBProfileSample).filter_by(profile_id=profile_id).first()
    if not sample:
        return
    audio_path = config.resolve_storage_path(sample.audio_path)
    if audio_path is None or not audio_path.exists():
        return

    analysis = await asyncio.to_thread(
        prosody_service.analyze_sample, str(audio_path), sample.reference_text
    )
    profile.default_emotion = analysis.emotion
    profile.default_speed = None  # clones carry their own pacing
    profile.default_pitch = 0
    if analysis.effects_chain and not profile.effects_chain:
        profile.effects_chain = _json.dumps(analysis.effects_chain)
    db.commit()


@router.get("/profiles/{profile_id}/samples", response_model=list[models.ProfileSampleResponse])
async def get_profile_samples(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get all samples for a profile."""
    return await profiles.get_profile_samples(profile_id, db)


@router.delete("/profiles/samples/{sample_id}")
async def delete_profile_sample(
    sample_id: str,
    db: Session = Depends(get_db),
):
    """Delete a profile sample."""
    success = await profiles.delete_profile_sample(sample_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"message": "Sample deleted successfully"}


@router.put("/profiles/samples/{sample_id}", response_model=models.ProfileSampleResponse)
async def update_profile_sample(
    sample_id: str,
    data: models.ProfileSampleUpdate,
    db: Session = Depends(get_db),
):
    """Update a profile sample's reference text."""
    sample = await profiles.update_profile_sample(sample_id, data.reference_text, db)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    return sample


@router.post("/profiles/{profile_id}/avatar", response_model=models.VoiceProfileResponse)
async def upload_profile_avatar(
    profile_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload or update avatar image for a profile."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "").suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        profile = await profiles.upload_avatar(profile_id, tmp_path, db)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/profiles/{profile_id}/avatar")
async def get_profile_avatar(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get avatar image for a profile."""
    profile = await profiles.get_profile(profile_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if not profile.avatar_path:
        raise HTTPException(status_code=404, detail="No avatar found for this profile")

    avatar_path = config.resolve_storage_path(profile.avatar_path)
    if avatar_path is None or not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Avatar file not found")

    return FileResponse(avatar_path)


@router.delete("/profiles/{profile_id}/avatar")
async def delete_profile_avatar(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Delete avatar image for a profile."""
    success = await profiles.delete_avatar(profile_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found or no avatar to delete")
    return {"message": "Avatar deleted successfully"}


@router.get("/profiles/{profile_id}/export")
async def export_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Export a voice profile as a ZIP archive."""
    try:
        profile = await profiles.get_profile(profile_id, db)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        zip_bytes = export_import.export_profile_to_zip(profile_id, db)

        safe_name = "".join(c for c in profile.name if c.isalnum() or c in (" ", "-", "_")).strip()
        if not safe_name:
            safe_name = "profile"
        filename = f"profile-{safe_name}.voicebox.zip"

        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": safe_content_disposition("attachment", filename)},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiles/{profile_id}/channels")
async def get_profile_channels(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get list of channel IDs assigned to a profile."""
    try:
        channel_ids = await channels.get_profile_channels(profile_id, db)
        return {"channel_ids": channel_ids}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/profiles/{profile_id}/channels")
async def set_profile_channels(
    profile_id: str,
    data: models.ProfileChannelAssignment,
    db: Session = Depends(get_db),
):
    """Set which channels a profile is assigned to."""
    try:
        await channels.set_profile_channels(profile_id, data, db)
        return {"message": "Profile channels updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/profiles/{profile_id}/effects", response_model=models.VoiceProfileResponse)
async def update_profile_effects(
    profile_id: str,
    data: models.ProfileEffectsUpdate,
    db: Session = Depends(get_db),
):
    """Set or clear the default effects chain for a voice profile."""
    profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if data.effects_chain is not None:
        from ..utils.effects import validate_effects_chain

        chain_dicts = [e.model_dump() for e in data.effects_chain]
        error = validate_effects_chain(chain_dicts)
        if error:
            raise HTTPException(status_code=400, detail=error)
        profile.effects_chain = _json.dumps(chain_dicts)
    else:
        profile.effects_chain = None

    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)

    return _profile_to_response(profile)


# ── Personality endpoint ──────────────────────────────────────────────
# Only ``/profiles/{id}/compose`` remains — the UI's compose button
# produces a fresh in-character utterance the user can edit before
# speaking. Rewrite now happens inside ``/generate`` (and ``/speak``)
# when ``personality=true``; there is no standalone rewrite/respond/speak
# endpoint.


@router.post(
    "/profiles/{profile_id}/compose",
    response_model=models.PersonalityTextResponse,
)
async def compose_in_character(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Produce a fresh utterance in the profile's character voice."""
    profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        result = await personality.compose_as_profile(profile.personality)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return models.PersonalityTextResponse(
        text=result.text, model_size=result.model_size
    )
