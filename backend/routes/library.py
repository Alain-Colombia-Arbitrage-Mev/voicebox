"""Public audio-library API — machine-consumable access to created audio.

Read-only endpoints for external apps (websites, scripts, agents) to list
and download the audio produced in Voicebox: soundscapes, tuned
frequencies/bells, breathing guides, imports and (optionally) voice
generations. These endpoints send permissive CORS headers so a browser
app on any origin can consume them without opening up the rest of the
API. The server binds 127.0.0.1 by default — start it with
``--host 0.0.0.0`` (or set VOICEBOX_CORS_ORIGINS) to serve other devices.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models
from ..database import Generation as DBGeneration, VoiceProfile as DBVoiceProfile, get_db

router = APIRouter()

# Bank profiles and the base category their generations belong to
_BANK_PROFILES = {
    "Meditation Music": "soundscape",
    "Frequencies": "frequency",
    "Imported Audio": "imported",
}

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "public, max-age=60",
}


def _category_for(profile_name: str, title: str) -> str:
    base = _BANK_PROFILES.get(profile_name, "voice")
    if base == "soundscape":
        return base
    lowered = title.lower()
    # Frequency-profile items and imports both categorize by title so a
    # library migrated through /generate/import keeps meaningful categories.
    if "respiración" in lowered or "respiracion" in lowered or "breathing" in lowered:
        return "breathing"
    if "campana" in lowered or "gong" in lowered or "bell" in lowered:
        return "bells"
    if base == "frequency" or "hz" in lowered or "schumann" in lowered:
        return "frequency"
    if base == "imported":
        return "soundscape" if any(
            k in lowered for k in ("soundscape", "meditation", "ambien", "rain", "ocean", "forest", "drone", "handpan", "bowls")
        ) else "imported"
    return base


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return re.sub(r"-+", "-", slug).strip("-")[:60] or "audio"


@router.get("/library", response_model=models.LibraryResponse)
async def list_library(
    response: Response,
    category: str | None = None,
    search: str | None = None,
    include_voices: bool = False,
    db: Session = Depends(get_db),
):
    """List the audio library with metadata and download URLs.

    Categories: soundscape, frequency, bells, breathing, imported — plus
    voice (every TTS generation) when ``include_voices`` is true.
    """
    for k, v in _CORS_HEADERS.items():
        response.headers[k] = v

    rows = (
        db.query(DBGeneration, DBVoiceProfile.name)
        .join(DBVoiceProfile, DBGeneration.profile_id == DBVoiceProfile.id)
        .filter(DBGeneration.status == "completed")
        .order_by(DBGeneration.created_at.desc())
        .all()
    )

    items: list[models.LibraryItem] = []
    for gen, profile_name in rows:
        in_bank = profile_name in _BANK_PROFILES
        if not in_bank and not include_voices:
            continue
        cat = _category_for(profile_name, gen.text or "")
        if category and cat != category:
            continue
        title = (gen.text or "").strip()
        if search and search.lower() not in title.lower() and search.lower() not in profile_name.lower():
            continue
        items.append(
            models.LibraryItem(
                id=gen.id,
                title=title[:200],
                category=cat,
                voice=None if in_bank else profile_name,
                duration_sec=round(gen.duration or 0, 1),
                created_at=gen.created_at,
                audio_url=f"/library/{gen.id}/audio",
                filename=f"{_slugify(title)}.wav",
            )
        )

    return models.LibraryResponse(
        items=items,
        total=len(items),
        categories=sorted({i.category for i in items}),
    )


@router.get("/library/{generation_id}/audio")
async def download_library_audio(generation_id: str, db: Session = Depends(get_db)):
    """Stream/download one library audio as WAV with a clean filename."""
    gen = db.query(DBGeneration).filter_by(id=generation_id, status="completed").first()
    if not gen or not gen.audio_path:
        raise HTTPException(status_code=404, detail="Audio not found")
    path = config.resolve_storage_path(gen.audio_path)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing on disk")

    filename = f"{_slugify(gen.text or generation_id)}{path.suffix or '.wav'}"
    return FileResponse(
        str(path),
        media_type="audio/wav" if path.suffix == ".wav" else "application/octet-stream",
        filename=filename,
        headers=_CORS_HEADERS,
    )


@router.options("/library")
@router.options("/library/{generation_id}/audio")
async def library_preflight(generation_id: str | None = None):
    """CORS preflight for browser consumers on any origin."""
    return Response(status_code=204, headers=_CORS_HEADERS)
