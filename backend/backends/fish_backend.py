"""Fish Audio hosted S2 TTS. No local model weights or Fish SDK required."""

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np

FISH_SAMPLE_RATE = 44100
FISH_API_HOST = "https://api.fish.audio"
DEFAULT_FISH_MODEL = "s2.1-pro"


class FishTTSBackend:
    PROSODY_PARAMS = ("emotion", "speed")

    def __init__(self):
        self.model_size = "default"

    def _get_settings(self):
        import os
        from ..database import get_db
        from ..services.settings import get_fish_settings

        db = next(get_db())
        try:
            row = get_fish_settings(db)
            key = row.api_key or os.environ.get("FISH_AUDIO_API_KEY")
            if not key:
                raise RuntimeError("Configure Fish Audio in Settings → Generation or FISH_AUDIO_API_KEY.")
            return {"api_key": key, "model": row.model or DEFAULT_FISH_MODEL}
        finally:
            db.close()

    @staticmethod
    def _check_response(response):
        # Never propagate provider bodies (which can contain input or credentials).
        if response.is_error:
            hints = {401: "check the API key", 402: "insufficient API credits (separate from platform credits)", 429: "rate limit reached"}
            hint = hints.get(response.status_code, "provider request failed")
            raise RuntimeError(f"Fish Audio HTTP {response.status_code}: {hint}")

    def is_loaded(self) -> bool:
        return True

    async def load_model(self, model_size: str = "default") -> None:
        self._get_settings()

    def unload_model(self) -> None:
        pass

    def _get_model_path(self, model_size: str = "default") -> str:
        return "fish-cloud"

    def _is_model_cached(self, model_size: str = "default") -> bool:
        return True

    async def create_voice_prompt(self, audio_path: str, reference_text: str, use_cache: bool = True):
        import httpx
        from ..database import FishVoice, get_db

        settings = self._get_settings()
        account = hashlib.sha256(settings["api_key"].encode()).hexdigest()
        content = Path(audio_path).read_bytes()
        cache_key = hashlib.sha256(account.encode() + content + reference_text.encode()).hexdigest()
        db = next(get_db())
        try:
            row = db.query(FishVoice).filter_by(sample_hash=cache_key).first() if use_cache else None
            if row:
                return {"fish_voice_id": row.voice_id, "engine": "fish"}, True
        finally:
            db.close()

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                FISH_API_HOST + "/model",
                headers={"Authorization": f"Bearer {settings['api_key']}"},
                data={"type": "tts", "title": "Voicebox " + cache_key[:12], "train_mode": "fast",
                      "visibility": "private", "texts": reference_text, "generate_sample": "false"},
                files={"voices": (Path(audio_path).name, content, "audio/wav")},
            )
        self._check_response(response)
        voice_id = response.json().get("_id")
        if not voice_id:
            raise RuntimeError("Fish Audio did not return a voice model ID")
        db = next(get_db())
        try:
            db.add(FishVoice(sample_hash=cache_key, voice_id=voice_id))
            db.commit()
        finally:
            db.close()
        return {"fish_voice_id": voice_id, "engine": "fish"}, False

    async def combine_voice_prompts(self, audio_paths: list[str], reference_texts: list[str]):
        from .base import combine_voice_prompts
        return await combine_voice_prompts(audio_paths, reference_texts, sample_rate=24000)

    async def generate(
        self, text: str, voice_prompt: dict, language: str = "es",
        seed: Optional[int] = None, instruct: Optional[str] = None,
        emotion: Optional[str] = None, speed: Optional[float] = None,
    ) -> tuple[np.ndarray, int]:
        import httpx
        from ..utils.directed_speech import render_with_pauses

        voice_id = voice_prompt.get("fish_voice_id") or voice_prompt.get("preset_voice_id")
        if not voice_id:
            raise RuntimeError("Fish Audio requires a cloned voice or a Fish voice model ID")
        settings = self._get_settings()
        # S2 consumes concise direction as inline cues, not a separate prompt.
        direction = (instruct or "").strip().replace("[", "").replace("]", "")
        cues = f"[{direction}] " if direction else ""
        if emotion:
            cues += f"[{'whispering' if emotion == 'whisper' else 'relaxed' if emotion == 'fluent' else emotion}] "

        async def synthesize(phrase):
            payload = {
                "text": cues + phrase, "reference_id": voice_id,
                "format": "pcm", "sample_rate": FISH_SAMPLE_RATE,
                "latency": "normal", "normalize": False,
                "temperature": 0.7, "top_p": 0.7,
                "prosody": {"speed": speed if speed is not None else 1.0, "volume": 0},
            }
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    FISH_API_HOST + "/v1/tts",
                    headers={"Authorization": f"Bearer {settings['api_key']}", "model": settings["model"]},
                    json=payload,
                )
            self._check_response(response)
            if not response.content or len(response.content) % 2 or "json" in response.headers.get("content-type", ""):
                raise RuntimeError("Fish Audio returned invalid PCM audio")
            audio = np.frombuffer(response.content, dtype="<i2").astype(np.float32) / 32768.0
            return audio, FISH_SAMPLE_RATE

        return await render_with_pauses(text, synthesize, FISH_SAMPLE_RATE)
