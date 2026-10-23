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

import hashlib
import logging
import re
import uuid
from typing import Optional

import numpy as np

from ..services import breath
from ..utils.cache import get_cache_key, get_cached_voice_prompt, cache_voice_prompt
from .base import combine_voice_prompts as _combine_voice_prompts

logger = logging.getLogger(__name__)

# PCM output keeps decoding dependency-free: hex → int16 → float32.
# 44.1 kHz is the highest rate the API offers; the extra headroom matters
# once a de-esser and a limiter run over the result.
MINIMAX_SAMPLE_RATE = 44100

DEFAULT_MINIMAX_HOST = "https://api.minimax.io"
DEFAULT_MINIMAX_MODEL = "speech-2.8-hd"

# Voice design bills the preview by the character, so this is deliberately
# short: the audio is thrown away and only the voice_id is kept.
DESIGN_PREVIEW_TEXT = "Respira hondo y suelta el aire despacio."

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

# Model families that *perform* the markup instead of reading it aloud.
# Parenthesised interjections — (inhale), (sighs) — arrived with 2.8;
# native <#x#> pauses work from 2.6 on.
SOUND_TAG_MODELS = ("speech-2.8",)
NATIVE_PAUSE_MODELS = ("speech-2.8", "speech-2.6")

# voice_modify.sound_effects accepts at most one of these.
MINIMAX_SOUND_EFFECTS = {
    "spacious_echo",
    "auditorium_echo",
    "lofi_telephone",
    "robotic",
}

_VOICE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")

# Pause markers like <#1.5#> are handled locally: the text is split on
# them, each phrase is synthesized separately, and exact silences are
# inserted between. MiniMax never sees the markers — cloned voices were
# reading them aloud / paraphrasing around them.
_PAUSE_MARKER_RE = re.compile(r"\s*<#(\d+(?:\.\d+)?)#>\s*")

# MiniMax status codes that mean "this voice_id no longer exists remotely"
# (expired unused clone, account cleanup, region switch). Triggers re-clone.
_VOICE_GONE_CODES = {2054}


class MiniMaxAPIError(RuntimeError):
    """MiniMax base_resp error carrying the numeric status code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class MiniMaxTTSBackend:
    """MiniMax Speech cloud backend — remote TTS + instant voice cloning."""

    # Extra generate() kwargs this backend honors; generate_chunked only
    # forwards prosody params to backends that declare them.
    PROSODY_PARAMS = (
        "emotion",
        "speed",
        "pitch",
        "vol",
        "breath_style",
        "intensity",
        "timbre",
        "sound_effects",
        "text_normalization",
    )

    def __init__(self):
        self.model_size = "default"

    # ── Settings ──────────────────────────────────────────────────────

    def _get_settings(self):
        """Read the MiniMax provider settings row. Raises if no API key.

        Environment variables act as fallback for headless deployments
        (Railway, Docker) so a fresh instance works without touching the
        settings endpoint, and a wiped volume doesn't lose the credential.
        DB values, when present, take precedence.
        """
        import os

        from ..database import get_db
        from ..services.settings import get_minimax_settings

        db = next(get_db())
        try:
            row = get_minimax_settings(db)
            api_key = row.api_key or os.environ.get("MINIMAX_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "MiniMax API key not configured. Add it in Settings → MiniMax "
                    "or set the MINIMAX_API_KEY environment variable."
                )
            return {
                "api_key": api_key,
                "group_id": row.group_id or os.environ.get("MINIMAX_GROUP_ID"),
                "host": (row.api_host or os.environ.get("MINIMAX_API_HOST") or DEFAULT_MINIMAX_HOST).rstrip("/"),
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
            raise MiniMaxAPIError(code, f"MiniMax {action} failed ({code}): {msg}")

    # ── Clone registry (SQLite) ───────────────────────────────────────
    # The torch prompt cache can be wiped by "clear cache"; the registry
    # row survives, so the same sample never gets re-cloned (and re-billed).

    @staticmethod
    def _registry_lookup(sample_hash: str) -> Optional[str]:
        from ..database import MiniMaxVoice, get_db

        db = next(get_db())
        try:
            row = db.query(MiniMaxVoice).filter_by(sample_hash=sample_hash).first()
            return row.voice_id if row else None
        finally:
            db.close()

    @staticmethod
    def _registry_save(voice_id: str, sample_hash: str) -> None:
        from ..database import MiniMaxVoice, get_db

        db = next(get_db())
        try:
            if not db.query(MiniMaxVoice).filter_by(voice_id=voice_id).first():
                db.add(MiniMaxVoice(voice_id=voice_id, sample_hash=sample_hash))
                db.commit()
        finally:
            db.close()

    @staticmethod
    def _registry_delete(voice_id: str) -> None:
        from ..database import MiniMaxVoice, get_db

        db = next(get_db())
        try:
            db.query(MiniMaxVoice).filter_by(voice_id=voice_id).delete()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _registry_touch(voice_id: str) -> None:
        """Record that the voice was just used — feeds the anti-expiration
        keepalive. Best-effort: never let bookkeeping break a generation."""
        from datetime import datetime

        from ..database import MiniMaxVoice, get_db

        try:
            db = next(get_db())
            try:
                row = db.query(MiniMaxVoice).filter_by(voice_id=voice_id).first()
                if row:
                    row.last_used_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("Failed to touch minimax voice %s", voice_id, exc_info=True)

    # ── Voice design ──────────────────────────────────────────────────

    async def create_designed_voice(
        self,
        design_prompt: str,
        use_cache: bool = True,
    ) -> tuple[dict, bool]:
        """Turn a written description into a reusable remote voice.

        Unlike cloning there is no reference audio: MiniMax invents the
        voice from *design_prompt*. The resulting voice_id is registered
        exactly like a clone, so the same description is never designed —
        or billed — twice.

        Returns:
            Tuple of (voice_prompt, was_cached).
        """
        normalized = " ".join(design_prompt.split())
        if not normalized:
            raise ValueError("Voice design requires a non-empty prompt")

        design_hash = hashlib.sha256(normalized.encode()).hexdigest()
        cache_key = ("minimax_design_" + design_hash) if use_cache else None

        def _build_prompt(voice_id: str) -> dict:
            return {
                "voice_type": "designed_remote",
                "engine": "minimax",
                "minimax_voice_id": voice_id,
                "sample_hash": design_hash,
                "design_prompt": normalized,
            }

        if cache_key:
            cached = get_cached_voice_prompt(cache_key)
            if isinstance(cached, dict) and cached.get("minimax_voice_id"):
                self._registry_save(cached["minimax_voice_id"], design_hash)
                return _build_prompt(cached["minimax_voice_id"]), True

        registered = self._registry_lookup(design_hash)
        if registered:
            voice_prompt = _build_prompt(registered)
            if cache_key:
                cache_voice_prompt(cache_key, voice_prompt)
            return voice_prompt, True

        settings = self._get_settings()
        voice_id = await self._design_voice(settings, normalized)
        self._registry_save(voice_id, design_hash)

        voice_prompt = _build_prompt(voice_id)
        if cache_key:
            cache_voice_prompt(cache_key, voice_prompt)
        return voice_prompt, False

    async def _design_voice(self, settings: dict, design_prompt: str) -> str:
        import httpx

        payload = {
            "prompt": design_prompt,
            # The preview is billed by character, so keep it short. It is
            # discarded — the voice_id is what we are after.
            "preview_text": DESIGN_PREVIEW_TEXT,
            "voice_id": "vbd" + _VOICE_ID_RE.sub("", uuid.uuid4().hex)[:21],
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            response = await client.post(
                self._url(settings, "/v1/voice_design"),
                headers={**self._headers(settings), "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        self._check_base_resp(body, "voice design")

        voice_id = body.get("voice_id")
        if not voice_id:
            raise RuntimeError("MiniMax voice design returned no voice_id")

        logger.info("MiniMax voice designed: %s", voice_id)
        return voice_id

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

    # ── Model capabilities ────────────────────────────────────────────

    @staticmethod
    def supports_sound_tags(model: str) -> bool:
        return model.startswith(SOUND_TAG_MODELS)

    @staticmethod
    def supports_native_pauses(model: str) -> bool:
        return model.startswith(NATIVE_PAUSE_MODELS)

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
        sample_hash = get_cache_key(audio_path, reference_text)
        cache_key = ("minimax_" + sample_hash) if use_cache else None

        def _build_prompt(voice_id: str) -> dict:
            # ref_audio/ref_text ride along so generate() can re-clone and
            # self-heal if the remote voice_id has expired or been deleted.
            return {
                "voice_type": "cloned_remote",
                "engine": "minimax",
                "minimax_voice_id": voice_id,
                "sample_hash": sample_hash,
                "ref_audio": audio_path,
                "ref_text": reference_text,
            }

        if cache_key:
            cached = get_cached_voice_prompt(cache_key)
            if isinstance(cached, dict) and cached.get("minimax_voice_id"):
                voice_prompt = _build_prompt(cached["minimax_voice_id"])
                # Backfill the registry for clones made before it existed
                self._registry_save(cached["minimax_voice_id"], sample_hash)
                if cached != voice_prompt:
                    cache_voice_prompt(cache_key, voice_prompt)
                return voice_prompt, True

        # Registry survives cache clears — reuse the remote clone instead of
        # re-cloning (and re-billing) the same sample.
        registered = self._registry_lookup(sample_hash)
        if registered:
            voice_prompt = _build_prompt(registered)
            if cache_key:
                cache_voice_prompt(cache_key, voice_prompt)
            return voice_prompt, True

        settings = self._get_settings()
        voice_id = await self._clone_voice(settings, audio_path, reference_text)
        self._registry_save(voice_id, sample_hash)

        voice_prompt = _build_prompt(voice_id)
        if cache_key:
            cache_voice_prompt(cache_key, voice_prompt)
        return voice_prompt, False

    async def _clone_voice(
        self, settings: dict, audio_path: str, reference_text: Optional[str] = None
    ) -> str:
        import httpx

        # Deterministic-ish but unique id satisfying MiniMax constraints:
        # starts with a letter, 8-256 chars, [A-Za-z0-9_-], no trailing -/_.
        voice_id = "vb" + _VOICE_ID_RE.sub("", uuid.uuid4().hex)[:22]

        # Delivery-mimicry prompt: a <8s slice of the reference plus its
        # transcript makes the clone reproduce that exact interpretation —
        # pacing, breaths, intensity — not just the timbre. Best-effort:
        # cloning proceeds without it if slicing/transcription isn't possible.
        prompt_slice = await self._build_clone_prompt_slice(audio_path)

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

            clone_payload: dict = {"file_id": file_id, "voice_id": voice_id}

            if prompt_slice is not None:
                slice_path, prompt_text = prompt_slice
                try:
                    with open(slice_path, "rb") as f:
                        prompt_resp = await client.post(
                            self._url(settings, "/v1/files/upload"),
                            headers=self._headers(settings),
                            data={"purpose": "prompt_audio"},
                            files={"file": ("prompt.wav", f, "audio/wav")},
                        )
                    prompt_resp.raise_for_status()
                    prompt_json = prompt_resp.json()
                    self._check_base_resp(prompt_json, "prompt upload")
                    prompt_file_id = (prompt_json.get("file") or {}).get("file_id")
                    if prompt_file_id:
                        clone_payload["clone_prompt"] = {
                            "prompt_audio": prompt_file_id,
                            "prompt_text": prompt_text,
                        }
                        logger.info("MiniMax clone using delivery prompt slice")
                except Exception:
                    logger.warning("Clone prompt upload failed — cloning without it", exc_info=True)

            clone_resp = await client.post(
                self._url(settings, "/v1/voice_clone"),
                headers={**self._headers(settings), "Content-Type": "application/json"},
                json=clone_payload,
            )
            clone_resp.raise_for_status()
            clone_json = clone_resp.json()
            self._check_base_resp(clone_json, "voice clone")

        logger.info("MiniMax voice cloned: %s", voice_id)
        return voice_id

    @staticmethod
    async def _build_clone_prompt_slice(audio_path: str) -> Optional[tuple[str, str]]:
        """Cut a ≤7.5s voiced slice of the reference and transcribe it locally.

        Returns (slice_path, transcript) or None. Uses the local Whisper
        model only if it's already downloaded — never triggers a download
        from inside a cloning call.
        """
        import asyncio

        try:
            from ..services.transcribe import get_whisper_model

            whisper = get_whisper_model()
            checker = getattr(whisper, "_is_model_cached", None)
            whisper_size = getattr(whisper, "model_size", None) or "base"
            if checker is not None and not checker(whisper_size):
                logger.info("Whisper not downloaded — skipping clone prompt slice")
                return None

            def _slice() -> Optional[str]:
                import librosa
                import soundfile as sf

                from .. import config

                y, sr = librosa.load(audio_path, sr=24000, mono=True)
                y, _ = librosa.effects.trim(y, top_db=30)
                max_n = int(7.5 * sr)
                if len(y) < sr * 2:
                    return None  # too short to be a useful delivery example
                seg = y[:max_n]
                out = config.get_cache_dir() / f"clone_prompt_{uuid.uuid4().hex[:8]}.wav"
                out.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(out), seg, sr)
                return str(out)

            slice_path = await asyncio.to_thread(_slice)
            if slice_path is None:
                return None

            transcript = await whisper.transcribe(slice_path)
            transcript = (transcript or "").strip()
            if not transcript:
                return None
            return slice_path, transcript
        except Exception:
            logger.warning("Could not build clone prompt slice", exc_info=True)
            return None

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
        vol: Optional[float] = None,
        breath_style: Optional[str] = None,
        intensity: Optional[int] = None,
        timbre: Optional[int] = None,
        sound_effects: Optional[str] = None,
        text_normalization: Optional[bool] = None,
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
            vol: Loudness multiplier in (0, 10]
            breath_style: Key of ``services.breath.BREATH_STYLES``. Scripts
                the text with audible breaths and held silences before it
                reaches the API.
            intensity: voice_modify intensity in [-100, 100]; negative is
                softer — the meditation register without touching the clone
            timbre: voice_modify timbre in [-100, 100]; negative is fuller
            sound_effects: One of MINIMAX_SOUND_EFFECTS
            text_normalization: Read digits and units as words. Defaults on:
                these scripts are full of "4 segundos" and "528 Hz".

        Returns:
            Tuple of (audio_array, sample_rate)
        """
        voice_id = voice_prompt.get("minimax_voice_id") or voice_prompt.get("preset_voice_id")
        if not voice_id:
            raise RuntimeError("MiniMax voice prompt is missing a voice_id")

        settings = self._get_settings()
        model = settings["model"]

        # Breath scripting runs first: everything below reasons about the
        # markers it produces.
        text = breath.annotate(
            text,
            breath_style or breath.DEFAULT_STYLE,
            sound_tags=self.supports_sound_tags(model),
        )
        if not self.supports_sound_tags(model):
            # An older model would spell "(inhale)" out loud.
            text = breath.strip_markup(text, pauses=False)

        options = {
            "emotion": emotion,
            "speed": speed,
            "pitch": pitch,
            "vol": vol,
            "intensity": intensity,
            "timbre": timbre,
            "sound_effects": sound_effects,
            "text_normalization": text_normalization,
        }

        # Pause handling. 2.6+ performs <#x#> inside a single request, which
        # keeps one prosodic arc across the whole piece. Older models get the
        # local fallback: split on the markers, synthesize each phrase and
        # splice exact silences — accurate, but every phrase restarts its
        # intonation, so an affirmation reads like a list.
        if not self.supports_native_pauses(model):
            parts = _PAUSE_MARKER_RE.split(text)
            if len(parts) > 1:
                return await self._generate_split_on_pauses(
                    parts, voice_prompt, language, seed, instruct, options
                )

        try:
            return await self._generate_with_voice(
                settings, voice_id, text, language, options,
                is_clone=bool(voice_prompt.get("minimax_voice_id")),
            )
        except MiniMaxAPIError as e:
            # Self-heal: the remote clone no longer exists (expired unused,
            # account cleanup…). Re-clone from the reference sample kept in
            # the voice prompt and retry once.
            can_reclone = (
                e.code in _VOICE_GONE_CODES
                and voice_prompt.get("minimax_voice_id")
                and voice_prompt.get("ref_audio")
            )
            if not can_reclone:
                raise
            logger.warning(
                "MiniMax voice %s no longer exists remotely — re-cloning from reference",
                voice_id,
            )
            self._registry_delete(voice_id)
            new_voice_id = await self._clone_voice(
                settings, voice_prompt["ref_audio"], voice_prompt.get("ref_text")
            )
            sample_hash = voice_prompt.get("sample_hash")
            if sample_hash:
                self._registry_save(new_voice_id, sample_hash)
                refreshed = dict(voice_prompt, minimax_voice_id=new_voice_id)
                cache_voice_prompt("minimax_" + sample_hash, refreshed)
            return await self._generate_with_voice(
                settings, new_voice_id, text, language, options, is_clone=True,
            )

    async def _generate_split_on_pauses(
        self,
        parts: list[str],
        voice_prompt: dict,
        language: str,
        seed: Optional[int],
        instruct: Optional[str],
        options: dict,
    ) -> tuple[np.ndarray, int]:
        """Synthesize each phrase separately and splice exact silences.

        ``parts`` alternates text and captured pause durations, as produced
        by ``_PAUSE_MARKER_RE.split``. Used only for models that cannot
        perform the markers themselves.
        """
        segments: list[np.ndarray] = []
        sample_rate = MINIMAX_SAMPLE_RATE
        for i, part in enumerate(parts):
            if i % 2 == 1:  # odd indexes are the captured pause durations
                pause_sec = min(float(part), 30.0)
                segments.append(np.zeros(int(pause_sec * sample_rate), dtype=np.float32))
                continue
            if not part.strip():
                continue
            seg_audio, sample_rate = await self.generate(
                part.strip(), voice_prompt, language, seed, instruct,
                # The script is already written; re-annotating each phrase
                # would add breaths the author never asked for.
                breath_style="off",
                **{k: v for k, v in options.items() if k != "breath_style"},
            )
            segments.append(np.asarray(seg_audio, dtype=np.float32))
        if not segments:
            raise RuntimeError("Pause-marker text contained no speakable segments")
        return np.concatenate(segments), sample_rate

    async def _generate_with_voice(
        self,
        settings: dict,
        voice_id: str,
        text: str,
        language: str,
        options: dict,
        *,
        is_clone: bool,
    ) -> tuple[np.ndarray, int]:
        import httpx

        emotion = options.get("emotion")
        speed = options.get("speed")
        pitch = options.get("pitch")
        vol = options.get("vol")

        voice_setting: dict = {"voice_id": voice_id}
        if speed is not None:
            voice_setting["speed"] = max(0.5, min(2.0, float(speed)))
        if pitch is not None:
            voice_setting["pitch"] = max(-12, min(12, int(pitch)))
        if vol is not None:
            # (0, 10] — zero would be silence, so clamp just above it.
            voice_setting["vol"] = max(0.01, min(10.0, float(vol)))
        if emotion and emotion in MINIMAX_EMOTIONS:
            voice_setting["emotion"] = emotion

        # Digits and units ("4 segundos", "528 Hz", "día 1") are read as
        # words instead of spelled out character by character.
        text_normalization = options.get("text_normalization")
        voice_setting["text_normalization"] = (
            True if text_normalization is None else bool(text_normalization)
        )

        # whisper/fluent are 2.6-series exclusives — 2.8 rejects them with
        # 2013. Swap the model for this request so ASMR just works.
        model = settings["model"]
        if emotion in ("whisper", "fluent") and not model.startswith("speech-2.6"):
            model = "speech-2.6-hd"

        payload = {
            "model": model,
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

        voice_modify = _build_voice_modify(options)
        if voice_modify:
            payload["voice_modify"] = voice_modify
            # The API rejects voice_modify alongside raw PCM (2013). WAV is
            # the same samples with a header, and soundfile is already a
            # dependency, so only the decode below changes.
            payload["audio_setting"]["format"] = "wav"

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

        raw = bytes.fromhex(audio_hex)
        sample_rate = (body.get("extra_info") or {}).get("audio_sample_rate") or MINIMAX_SAMPLE_RATE

        if payload["audio_setting"]["format"] == "wav":
            import io

            import soundfile as sf

            audio, sample_rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
        else:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        if is_clone:
            self._registry_touch(voice_id)

        return audio, int(sample_rate)


def _build_voice_modify(options: dict) -> dict:
    """Assemble voice_modify from the delivery options that are set.

    These reshape the *performance* — softer, fuller, more spacious —
    without re-cloning, which is why they are preferred over pitch
    shifting for registers like meditation.
    """
    modify: dict = {}
    for key in ("intensity", "timbre"):
        value = options.get(key)
        if value is not None:
            modify[key] = max(-100, min(100, int(value)))

    effect = options.get("sound_effects")
    if effect:
        if effect not in MINIMAX_SOUND_EFFECTS:
            raise ValueError(
                f"Unknown MiniMax sound effect {effect!r}. "
                f"Available: {sorted(MINIMAX_SOUND_EFFECTS)}"
            )
        modify["sound_effects"] = effect

    return modify


# ── Anti-expiration keepalive ─────────────────────────────────────────
# MiniMax retains a cloned voice indefinitely once it has been used, but
# deletes clones that stay unused. To keep every registered clone alive
# regardless, voices idle for KEEPALIVE_AFTER_DAYS get touched with a
# minimal synthesis request on server startup (fractions of a cent each).

KEEPALIVE_AFTER_DAYS = 4
KEEPALIVE_MAX_PER_RUN = 20


async def refresh_stale_voices() -> None:
    """Touch cloned voices that haven't been used recently so they never
    expire remotely. Silent no-op without an API key. Runs at startup."""
    from datetime import datetime, timedelta

    from ..database import MiniMaxVoice, get_db

    backend = MiniMaxTTSBackend()
    try:
        settings = backend._get_settings()
    except Exception:
        return  # not configured — nothing to keep alive

    cutoff = datetime.utcnow() - timedelta(days=KEEPALIVE_AFTER_DAYS)
    db = next(get_db())
    try:
        stale = (
            db.query(MiniMaxVoice)
            .filter(MiniMaxVoice.last_used_at < cutoff)
            .limit(KEEPALIVE_MAX_PER_RUN)
            .all()
        )
        voice_ids = [row.voice_id for row in stale]
    finally:
        db.close()

    if not voice_ids:
        return

    logger.info("MiniMax keepalive: touching %d idle cloned voice(s)", len(voice_ids))
    for voice_id in voice_ids:
        try:
            await backend._generate_with_voice(
                settings, voice_id, "om", "en", {}, is_clone=True
            )
        except MiniMaxAPIError as e:
            if e.code in _VOICE_GONE_CODES:
                # Already gone remotely — drop the row; the self-heal path
                # re-clones from the reference on next real use.
                logger.warning("MiniMax voice %s already expired — unregistering", voice_id)
                backend._registry_delete(voice_id)
            else:
                logger.warning("MiniMax keepalive failed for %s: %s", voice_id, e)
        except Exception as e:
            logger.warning("MiniMax keepalive failed for %s: %s", voice_id, e)
