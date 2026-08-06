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
    """POST /v1/music_generation and return the decoded audio bytes.

    Renders normally take 1-4 minutes but spike well past 10 under load,
    so the read timeout is generous and a timed-out request gets one
    retry before giving up.
    """
    import httpx

    from ..backends.minimax_backend import MiniMaxTTSBackend

    backend = MiniMaxTTSBackend()
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(1200.0, connect=30.0)) as client:
                resp = await client.post(
                    backend._url(settings, "/v1/music_generation"),
                    headers={**backend._headers(settings), "Content-Type": "application/json"},
                    json=payload,
                )
            resp.raise_for_status()
            break
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_error = e
            logger.warning("MiniMax music render timed out (attempt %d/2)", attempt + 1)
    else:
        raise RuntimeError("MiniMax music generation timed out after retry") from last_error

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


async def run_frequency_music_generation(
    *,
    generation_id: str,
    music_prompt: str,
    carrier_hz: float,
    beat_hz: float,
    mode: str,
    duration_sec: float,
    tone_volume: float,
) -> None:
    """Generate MiniMax ambient music and infuse the exact frequency into it.

    Same lifecycle as run_music_generation — enqueued on the serial queue,
    persists onto a pre-created generation row.
    """
    import io

    import soundfile as sf

    from ..backends.minimax_backend import MiniMaxTTSBackend
    from .frequencies import infuse_tone_into_music

    task_manager = get_task_manager()
    bg_db = next(get_db())
    try:
        settings = MiniMaxTTSBackend()._get_settings()

        payload: dict = {
            "model": DEFAULT_MUSIC_MODEL,
            "prompt": music_prompt,
            "is_instrumental": True,
            "output_format": "hex",
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "wav",
            },
        }
        try:
            audio_bytes = await _call_music_api(settings, payload)
        except RuntimeError as e:
            if "2056" in str(e):
                logger.info("Music plan limit hit — retrying with %s", FREE_MUSIC_MODEL)
                payload["model"] = FREE_MUSIC_MODEL
                audio_bytes = await _call_music_api(settings, payload)
            else:
                raise

        music, music_sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")

        mixed = infuse_tone_into_music(
            music,
            int(music_sr),
            carrier_hz=carrier_hz,
            beat_hz=beat_hz,
            mode=mode,
            duration_sec=duration_sec,
            tone_volume=tone_volume,
        )

        from ..utils.audio import save_audio

        target = config.get_generations_dir() / f"{generation_id}.wav"
        save_audio(mixed, str(target), int(music_sr))

        await history.update_generation_status(
            generation_id=generation_id,
            status="completed",
            db=bg_db,
            audio_path=config.to_storage_path(target),
            duration=float(mixed.shape[0]) / float(music_sr),
        )
    except Exception as e:
        logger.exception("Frequency-music generation failed")
        await history.update_generation_status(
            generation_id=generation_id,
            status="failed",
            db=bg_db,
            error=str(e) or type(e).__name__,
        )
    finally:
        task_manager.complete_generation(generation_id)
        bg_db.close()
