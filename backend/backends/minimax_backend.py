"""
MiniMax cloud TTS backend implementation.

Wraps the MiniMax Speech API (speech-2.8 / speech-02 family) for
high-quality cloud TTS with instant voice cloning and per-generation
prosody control (emotion, speed, pitch).

Unlike the local engines there is nothing to download or load — the
"model" is a remote endpoint. Voice cloning works by uploading the
profile's reference audio once (POST /v1/files/upload with
purpose=voice_clone, then POST /v1/voice_clone); the resulting remote
voice_id is cached locally as the voice prompt and reused for every
generation.

Reference audio requirements (enforced server-side by MiniMax):
mp3/m4a/wav, 10 seconds to 5 minutes, max 20 MB.
"""

import logging
import re
import uuid
from typing import Optional

import numpy as np

from ..utils.cache import get_cache_key, get_cached_voice_prompt, cache_voice_prompt
from .base import combine_voice_prompts as _combine_voice_prompts

logger = logging.getLogger(__name__)

# PCM output keeps decoding dependency-free: hex → int16 → float32.
MINIMAX_SAMPLE_RATE = 32000

DEFAULT_MINIMAX_HOST = "https://api.minimax.io"
DEFAULT_MINIMAX_MODEL = "speech-2.8-hd"

# Emotions accepted by voice_setting.emotion. "fluent" and "whisper"
# need speech-2.6+; the API rejects them on older models.
MINIMAX_EMOTIONS = {
    "happy",
    "sad",
    "angry",
    "fearful",
    "disgusted",
    "surprised",
    "calm",
    "fluent",
    "whisper",
}

# System voices offered as presets: (voice_id, display_name, gender, lang)
MINIMAX_VOICES = [
    ("Wise_Woman", "Wise Woman", "female", "en"),
    ("Calm_Woman", "Calm Woman", "female", "en"),
    ("Inspirational_girl", "Inspirational Girl", "female", "en"),
    ("Lively_Girl", "Lively Girl", "female", "en"),
    ("Lovely_Girl", "Lovely Girl", "female", "en"),
    ("Sweet_Girl_2", "Sweet Girl", "female", "en"),
    ("Exuberant_Girl", "Exuberant Girl", "female", "en"),
    ("Abbess", "Abbess", "female", "en"),
    ("Friendly_Person", "Friendly Person", "female", "en"),
    ("Deep_Voice_Man", "Deep Voice Man", "male", "en"),
    ("Casual_Guy", "Casual Guy", "male", "en"),
    ("Patient_Man", "Patient Man", "male", "en"),
    ("Young_Knight", "Young Knight", "male", "en"),
    ("Determined_Man", "Determined Man", "male", "en"),
    ("Decent_Boy", "Decent Boy", "male", "en"),
    ("Imposing_Manner", "Imposing Manner", "male", "en"),
    ("Elegant_Man", "Elegant Man", "male", "en"),
    # Spanish system voices (IDs verified against the live API)
    ("Spanish_SereneWoman", "Serena (Español)", "female", "es"),
    ("Spanish_Kind-heartedGirl", "Bondadosa (Español)", "female", "es"),
    ("Spanish_ReservedYoungMan", "Joven Sereno (Español)", "male", "es"),
    ("Spanish_ThoughtfulMan", "Reflexivo (Español)", "male", "es"),
]

# ISO code → language_boost value. Missing codes fall back to "auto".
LANGUAGE_BOOST_MAP = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
    "he": "Hebrew",
    "ar": "Arabic",
    "da": "Danish",
    "el": "Greek",
    "fi": "Finnish",
    "hi": "Hindi",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "sv": "Swedish",
    "tr": "Turkish",
}

_VOICE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


class MiniMaxTTSBackend:
    """MiniMax Speech cloud backend — remote TTS + instant voice cloning."""

    # Extra generate() kwargs this backend honors; generate_chunked only
    # forwards prosody params to backends that declare them.
    PROSODY_PARAMS = ("emotion", "speed", "pitch")

    def __init__(self):
        self.model_size = "default"

    # ── Settings ──────────────────────────────────────────────────────

    def _get_settings(self):
        """Read the MiniMax provider settings row. Raises if no API key."""
        from ..database import get_db
        from ..services.settings import get_minimax_settings

        db = next(get_db())
        try:
            row = get_minimax_settings(db)
            if not row.api_key:
                raise RuntimeError(
                    "MiniMax API key not configured. Add it in Settings → MiniMax."
                )
            return {
                "api_key": row.api_key,
                "group_id": row.group_id,
                "host": (row.api_host or DEFAULT_MINIMAX_HOST).rstrip("/"),
                "model": row.model or DEFAULT_MINIMAX_MODEL,
            }
        finally:
            db.close()

    def _url(self, settings: dict, path: str) -> str:
        url = f"{settings['host']}{path}"
        if settings.get("group_id"):
            url += f"?GroupId={settings['group_id']}"
        return url

    @staticmethod
    def _headers(settings: dict) -> dict:
        return {"Authorization": f"Bearer {settings['api_key']}"}

    @staticmethod
    def _check_base_resp(payload: dict, action: str) -> None:
        base = payload.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code != 0:
            msg = base.get("status_msg") or "unknown error"
            if code == 1004:
                msg = "authentication failed — check your MiniMax API key"
            raise RuntimeError(f"MiniMax {action} failed ({code}): {msg}")

    # ── Model lifecycle (no-ops for a remote engine) ──────────────────

    def is_loaded(self) -> bool:
        # Nothing lives in memory; the engine is "loaded" whenever it's
        # reachable. Configuration errors surface in load_model().
        return True

    async def load_model(self, model_size: str = "default") -> None:
        """Validate configuration — a remote engine has nothing to load."""
        self._get_settings()

    def unload_model(self) -> None:
        pass

    def _get_model_path(self, model_size: str = "default") -> str:
        return "minimax-cloud"

    def _is_model_cached(self, model_size: str = "default") -> bool:
        return True

    # ── Voice cloning ─────────────────────────────────────────────────

    async def create_voice_prompt(
        self,
        audio_path: str,
        reference_text: str,
        use_cache: bool = True,
    ) -> tuple[dict, bool]:
        """Clone the reference audio on MiniMax and return the remote voice_id.

        The clone happens once per (audio, text) pair; afterwards the
        voice_id is cached locally like any other voice prompt.
        """
        cache_key = ("minimax_" + get_cache_key(audio_path, reference_text)) if use_cache else None

        if cache_key:
            cached = get_cached_voice_prompt(cache_key)
            if isinstance(cached, dict) and cached.get("minimax_voice_id"):
                return cached, True

        settings = self._get_settings()
        voice_id = await self._clone_voice(settings, audio_path)

        voice_prompt = {
            "voice_type": "cloned_remote",
            "engine": "minimax",
            "minimax_voice_id": voice_id,
        }
        if cache_key:
            cache_voice_prompt(cache_key, voice_prompt)
        return voice_prompt, False

    async def _clone_voice(self, settings: dict, audio_path: str) -> str:
        import httpx

        # Deterministic-ish but unique id satisfying MiniMax constraints:
        # starts with a letter, 8-256 chars, [A-Za-z0-9_-], no trailing -/_.
        voice_id = "vb" + _VOICE_ID_RE.sub("", uuid.uuid4().hex)[:22]

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            with open(audio_path, "rb") as f:
                upload_resp = await client.post(
                    self._url(settings, "/v1/files/upload"),
                    headers=self._headers(settings),
                    data={"purpose": "voice_clone"},
                    files={"file": (audio_path.split("/")[-1], f, "audio/wav")},
                )
            upload_resp.raise_for_status()
            upload_json = upload_resp.json()
            self._check_base_resp(upload_json, "file upload")
            file_id = (upload_json.get("file") or {}).get("file_id")
            if not file_id:
                raise RuntimeError("MiniMax file upload returned no file_id")

            clone_resp = await client.post(
                self._url(settings, "/v1/voice_clone"),
                headers={**self._headers(settings), "Content-Type": "application/json"},
                json={"file_id": file_id, "voice_id": voice_id},
            )
            clone_resp.raise_for_status()
            clone_json = clone_resp.json()
            self._check_base_resp(clone_json, "voice clone")

        logger.info("MiniMax voice cloned: %s", voice_id)
        return voice_id

    async def combine_voice_prompts(
        self,
        audio_paths: list[str],
        reference_texts: list[str],
    ) -> tuple[np.ndarray, str]:
        """Concatenate samples locally; the combined wav is cloned as one voice."""
        # 24 kHz matches the sample rate the profile service saves the
        # combined wav at before calling create_voice_prompt().
        return await _combine_voice_prompts(audio_paths, reference_texts, sample_rate=24000)

    # ── Generation ────────────────────────────────────────────────────

    async def generate(
        self,
        text: str,
        voice_prompt: dict,
        language: str = "en",
        seed: Optional[int] = None,
        instruct: Optional[str] = None,
        emotion: Optional[str] = None,
        speed: Optional[float] = None,
        pitch: Optional[int] = None,
    ) -> tuple[np.ndarray, int]:
        """
        Generate audio via the MiniMax t2a_v2 endpoint.

        Args:
            text: Text to synthesize
            voice_prompt: Dict with minimax_voice_id (cloned) or preset_voice_id
            language: ISO code mapped to language_boost
            seed: Not supported by the API (ignored)
            instruct: Not supported (ignored)
            emotion: One of MINIMAX_EMOTIONS, or None for auto
            speed: Speech rate in [0.5, 2.0]
            pitch: Semitone shift in [-12, 12]

        Returns:
            Tuple of (audio_array, sample_rate)
        """
        import httpx

        voice_id = voice_prompt.get("minimax_voice_id") or voice_prompt.get("preset_voice_id")
        if not voice_id:
            raise RuntimeError("MiniMax voice prompt is missing a voice_id")

        settings = self._get_settings()

        voice_setting: dict = {"voice_id": voice_id}
        if speed is not None:
            voice_setting["speed"] = max(0.5, min(2.0, float(speed)))
        if pitch is not None:
            voice_setting["pitch"] = max(-12, min(12, int(pitch)))
        if emotion and emotion in MINIMAX_EMOTIONS:
            voice_setting["emotion"] = emotion

        payload = {
            "model": settings["model"],
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": MINIMAX_SAMPLE_RATE,
                "format": "pcm",
                "channel": 1,
            },
            "language_boost": LANGUAGE_BOOST_MAP.get(language, "auto"),
            "output_format": "hex",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(
                self._url(settings, "/v1/t2a_v2"),
                headers={**self._headers(settings), "Content-Type": "application/json"},
                json=payload,
            )
        resp.raise_for_status()
        body = resp.json()
        self._check_base_resp(body, "speech generation")

        audio_hex = (body.get("data") or {}).get("audio")
        if not audio_hex:
            raise RuntimeError("MiniMax returned no audio data")

        pcm = np.frombuffer(bytes.fromhex(audio_hex), dtype=np.int16)
        audio = pcm.astype(np.float32) / 32768.0

        sample_rate = (body.get("extra_info") or {}).get("audio_sample_rate") or MINIMAX_SAMPLE_RATE
        return audio, int(sample_rate)
