"""
Background music generation via the MiniMax music API.

Generates instrumental (or sung) music from a style prompt and registers
the result as a regular Generation row under a singleton "Meditation
Music" profile — the same trick the audio-import flow uses — so music
clips show up in history and can be arranged on the story timeline next
to generated voices with the existing track/trim/volume tooling.
"""

from __future__ import annotations

import logging

from .. import config
from ..database import get_db
from . import history
from ..utils.tasks import get_task_manager

logger = logging.getLogger(__name__)

MUSIC_PROFILE_NAME = "Meditation Music"
DEFAULT_MUSIC_MODEL = "music-3.0"
# Free-tier fallback when the account's plan doesn't cover the paid model.
FREE_MUSIC_MODEL = "music-3.0-free"


async def _call_music_api(settings: dict, payload: dict) -> bytes:
    """POST /v1/music_generation and return the decoded audio bytes."""
    import httpx

    from ..backends.minimax_backend import MiniMaxTTSBackend

    backend = MiniMaxTTSBackend()
    # Music renders can take several minutes on the non-streaming endpoint.
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        resp = await client.post(
            backend._url(settings, "/v1/music_generation"),
            headers={**backend._headers(settings), "Content-Type": "application/json"},
            json=payload,
        )
    resp.raise_for_status()
    body = resp.json()
    backend._check_base_resp(body, "music generation")

    audio_hex = (body.get("data") or {}).get("audio")
    if not audio_hex:
        raise RuntimeError("MiniMax returned no music data")
    return bytes.fromhex(audio_hex)


async def run_music_generation(
    *,
    generation_id: str,
    prompt: str,
    lyrics: str | None,
    instrumental: bool,
    model: str | None,
) -> None:
    """Generate music and persist it on the pre-created generation row.

    Designed to be enqueued on the serial generation queue like TTS work.
    """
    from ..backends.minimax_backend import MiniMaxTTSBackend
    from ..utils.audio import load_audio

    task_manager = get_task_manager()
    bg_db = next(get_db())
    try:
        settings = MiniMaxTTSBackend()._get_settings()

        payload: dict = {
            "model": model or DEFAULT_MUSIC_MODEL,
            "prompt": prompt,
            "is_instrumental": instrumental,
            "output_format": "hex",
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "wav",
            },
        }
        if lyrics:
            payload["lyrics"] = lyrics

        try:
            audio_bytes = await _call_music_api(settings, payload)
        except RuntimeError as e:
            # Plan-limit errors: retry once on the free-tier model so the
            # feature still works for accounts without music credits.
            if model is None and "2056" in str(e):
                logger.info("Music plan limit hit — retrying with %s", FREE_MUSIC_MODEL)
                payload["model"] = FREE_MUSIC_MODEL
                audio_bytes = await _call_music_api(settings, payload)
            else:
                raise

        target = config.get_generations_dir() / f"{generation_id}.wav"
        target.write_bytes(audio_bytes)

        audio, sr = load_audio(str(target))
        duration = float(len(audio) / sr) if sr else 0.0

        await history.update_generation_status(
            generation_id=generation_id,
            status="completed",
            db=bg_db,
            audio_path=config.to_storage_path(target),
            duration=duration,
        )
    except Exception as e:
        logger.exception("Music generation failed")
        await history.update_generation_status(
            generation_id=generation_id,
            status="failed",
            db=bg_db,
            # Timeouts and friends stringify to "" — fall back to the type name
            error=str(e) or type(e).__name__,
        )
    finally:
        task_manager.complete_generation(generation_id)
        bg_db.close()
