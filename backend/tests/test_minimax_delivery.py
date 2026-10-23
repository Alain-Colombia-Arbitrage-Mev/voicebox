"""Tests for the MiniMax request the delivery controls produce.

These pin the payload, not the audio: which model gets sound tags, which
gets native pauses, and how the delivery options map onto voice_setting
and voice_modify. The HTTP layer is stubbed — the point is what we send.
"""

import numpy as np
import pytest

from backend.backends import minimax_backend
from backend.backends.minimax_backend import MiniMaxTTSBackend

PCM_HEX = np.zeros(8, dtype=np.int16).tobytes().hex()


def _wav_hex(sample_rate: int) -> str:
    """A real wav container — voice_modify requests get wav, not raw PCM."""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(np.zeros(8, dtype=np.int16).tobytes())
    return buffer.getvalue().hex()


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Captures every t2a_v2 payload sent inside one generate() call."""

    def __init__(self, sink, **kwargs):
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None, **kwargs):
        self._sink.append(json)
        sample_rate = minimax_backend.MINIMAX_SAMPLE_RATE
        audio_format = (json.get("audio_setting") or {}).get("format", "pcm")
        audio = _wav_hex(sample_rate) if audio_format == "wav" else PCM_HEX
        return _FakeResponse(
            {
                "base_resp": {"status_code": 0},
                "data": {"audio": audio},
                "extra_info": {"audio_sample_rate": sample_rate},
            }
        )


@pytest.fixture
def capture(monkeypatch):
    """Run generate() against a stubbed API and return the payloads sent."""
    sent: list[dict] = []

    class _Httpx:
        Timeout = lambda *a, **k: None  # noqa: E731 — only passed through

        @staticmethod
        def AsyncClient(**kwargs):
            return _FakeClient(sent, **kwargs)

    monkeypatch.setitem(__import__("sys").modules, "httpx", _Httpx)

    def _run(text, model="speech-2.8-hd", **options):
        import asyncio

        monkeypatch.setattr(
            MiniMaxTTSBackend,
            "_get_settings",
            lambda self: {
                "api_key": "test-key",
                "group_id": None,
                "host": "https://api.minimax.io",
                "model": model,
            },
        )
        sent.clear()
        asyncio.run(
            MiniMaxTTSBackend().generate(
                text,
                {"preset_voice_id": "Spanish_SereneWoman"},
                "es",
                **options,
            )
        )
        return sent

    return _run


# ── model capabilities ───────────────────────────────────────────────


def test_28_performs_pauses_in_a_single_request(capture):
    payloads = capture("Inhala hondo y suelta el aire.", breath_style="meditation")
    assert len(payloads) == 1, "one request keeps one prosodic arc"
    assert "<#" in payloads[0]["text"]
    assert "(inhale)" in payloads[0]["text"]


def test_older_model_splits_on_pauses_and_drops_tags(capture):
    payloads = capture(
        "Inhala hondo y suelta el aire.",
        model="speech-02-hd",
        breath_style="meditation",
    )
    assert len(payloads) > 1, "speech-02 cannot perform markers, so we splice"
    for payload in payloads:
        assert "<#" not in payload["text"]
        assert "(" not in payload["text"], "an older model would spell the tag out"


def test_26_gets_native_pauses_without_sound_tags(capture):
    payloads = capture(
        "Inhala hondo y suelta el aire.",
        model="speech-2.6-hd",
        breath_style="meditation",
    )
    assert len(payloads) == 1
    assert "<#" in payloads[0]["text"]
    assert "(inhale)" not in payloads[0]["text"]


def test_no_breath_style_leaves_the_text_alone(capture):
    text = "Inhala hondo y suelta el aire."
    assert capture(text)[0]["text"] == text


# ── delivery options ─────────────────────────────────────────────────


def test_text_normalization_defaults_on(capture):
    payload = capture("Respira durante 4 segundos.")[0]
    assert payload["voice_setting"]["text_normalization"] is True


def test_text_normalization_can_be_turned_off(capture):
    payload = capture("Respira.", text_normalization=False)[0]
    assert payload["voice_setting"]["text_normalization"] is False


def test_voice_modify_carries_intensity_and_timbre(capture):
    payload = capture("Respira.", intensity=-35, timbre=-10)[0]
    assert payload["voice_modify"] == {"intensity": -35, "timbre": -10}


def test_voice_modify_switches_off_pcm(capture):
    """The API rejects voice_modify alongside raw PCM with code 2013."""
    assert capture("Respira.", intensity=-35)[0]["audio_setting"]["format"] == "wav"


def test_plain_requests_stay_on_pcm(capture):
    assert capture("Respira.")[0]["audio_setting"]["format"] == "pcm"


def test_voice_modify_is_omitted_when_unset(capture):
    assert "voice_modify" not in capture("Respira.")[0]


def test_unknown_sound_effect_is_rejected(capture):
    with pytest.raises(ValueError, match="Unknown MiniMax sound effect"):
        capture("Respira.", sound_effects="cathedral")


def test_vol_is_clamped_above_silence(capture):
    payload = capture("Respira.", vol=0.0)[0]
    assert payload["voice_setting"]["vol"] == pytest.approx(0.01)


def test_requests_full_rate_audio(capture):
    assert capture("Respira.")[0]["audio_setting"]["sample_rate"] == 44100


# ── voice design ─────────────────────────────────────────────────────


@pytest.fixture
def design(monkeypatch):
    """Design a voice against a stubbed API and an in-memory registry."""
    sent: list[dict] = []
    registry: dict[str, str] = {}
    cache: dict[str, dict] = {}

    class _Httpx:
        Timeout = lambda *a, **k: None  # noqa: E731

        @staticmethod
        def AsyncClient(**kwargs):
            return _DesignClient(sent, **kwargs)

    class _DesignClient(_FakeClient):
        async def post(self, url, headers=None, json=None, **kwargs):
            self._sink.append(json)
            return _FakeResponse(
                {
                    "base_resp": {"status_code": 0},
                    "voice_id": json.get("voice_id") or "ttv-voice-generated",
                    "trial_audio": PCM_HEX,
                }
            )

    monkeypatch.setitem(__import__("sys").modules, "httpx", _Httpx)
    monkeypatch.setattr(MiniMaxTTSBackend, "_registry_lookup", staticmethod(registry.get))
    monkeypatch.setattr(
        MiniMaxTTSBackend,
        "_registry_save",
        staticmethod(lambda voice_id, sample_hash: registry.setdefault(sample_hash, voice_id)),
    )
    monkeypatch.setattr(minimax_backend, "get_cached_voice_prompt", cache.get)
    monkeypatch.setattr(
        minimax_backend, "cache_voice_prompt", lambda key, value: cache.__setitem__(key, value)
    )
    monkeypatch.setattr(
        MiniMaxTTSBackend,
        "_get_settings",
        lambda self: {
            "api_key": "test-key",
            "group_id": None,
            "host": "https://api.minimax.io",
            "model": "speech-2.8-hd",
        },
    )

    def _run(prompt, **kwargs):
        import asyncio

        return asyncio.run(MiniMaxTTSBackend().create_designed_voice(prompt, **kwargs)), sent

    return _run


def test_design_sends_prompt_and_a_short_preview(design):
    (prompt, cached), sent = design("Voz femenina española, grave y pausada")
    assert cached is False
    assert sent[0]["prompt"] == "Voz femenina española, grave y pausada"
    # The preview is billed per character, so it must stay small.
    assert 0 < len(sent[0]["preview_text"]) <= 100
    assert prompt["minimax_voice_id"] == sent[0]["voice_id"]
    assert prompt["voice_type"] == "designed_remote"


def test_same_description_is_never_designed_twice(design):
    design("Voz cálida para meditación")
    (_, cached), sent = design("Voz cálida para meditación")
    assert cached is True
    assert len(sent) == 1, "a second design call would be billed again"


def test_whitespace_differences_do_not_create_a_second_voice(design):
    design("Voz  cálida   para meditación")
    (_, cached), sent = design("Voz cálida para meditación\n")
    assert cached is True
    assert len(sent) == 1


def test_empty_description_is_rejected(design):
    with pytest.raises(ValueError, match="non-empty prompt"):
        design("   ")
