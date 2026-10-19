"""Saved voice-mastering chains must validate, save, preview and render."""

import hashlib
import io

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import config, database
from backend.routes import effects, profiles
from backend.utils.effects import apply_effects, validate_effects_chain


def effect(name, **params):
    return {"type": name, "enabled": True, "params": params}


# Configurations already saved by earlier versions of the Spanish voice studio.
SAVED_CHAINS = {
    "Voice Master": [
        effect("highpass", cutoff_frequency_hz=80.0),
        effect("deesser", frequency_hz=6500.0, threshold_db=-38.0, ratio=5.0),
        effect("compressor", threshold_db=-18.0, ratio=2.0, attack_ms=12.0, release_ms=180.0),
        effect("peak_eq", cutoff_frequency_hz=3000.0, gain_db=1.5, q=0.8),
    ],
    "Meditation Room": [
        effect("highpass", cutoff_frequency_hz=80.0),
        effect("deesser", frequency_hz=6500.0, threshold_db=-40.0, ratio=6.0),
        effect("compressor", threshold_db=-20.0, ratio=2.0, attack_ms=15.0, release_ms=250.0),
        effect("reverb", room_size=0.32, damping=0.6, wet_level=0.14, dry_level=0.9, width=0.8),
    ],
    "Meditation Voice": [
        effect("highpass", cutoff_frequency_hz=70.0),
        effect("deesser", frequency_hz=6500.0, threshold_db=-40.0, ratio=6.0),
        effect("compressor", threshold_db=-24.0, ratio=1.6, attack_ms=25.0, release_ms=400.0),
        effect("high_shelf", cutoff_frequency_hz=7000.0, gain_db=-2.0, q=0.7),
    ],
}


def tone(frequency, amplitude=0.2, sample_rate=48000):
    return (amplitude * np.sin(2 * np.pi * frequency * np.arange(sample_rate) / sample_rate)).astype(np.float32)


def gain_db(original, processed):
    # Ignore the initial attack and filter settling.
    start = len(original) // 2
    return 20 * np.log10(np.linalg.norm(processed[start:]) / np.linalg.norm(original[start:]))


def test_deesser_reduces_loud_highs_without_ducking_the_voice_body():
    low, high = tone(200), tone(10000)
    chain = [effect("deesser")]
    assert abs(gain_db(low, apply_effects(low, 48000, chain))) < 0.1
    assert gain_db(high, apply_effects(high, 48000, chain)) < -4.0


@pytest.mark.parametrize("amplitude,ratio", [(0.0001, 5.0), (0.2, 1.0)])
def test_deesser_recombines_transparently_without_compression(amplitude, ratio):
    audio = tone(10000, amplitude)
    processed = apply_effects(audio, 48000, [effect("deesser", ratio=ratio)])
    np.testing.assert_allclose(processed, audio, atol=1e-7)


@pytest.mark.parametrize("name", ["peak_eq", "high_shelf"])
def test_equalizers_really_change_the_selected_band(name):
    frequency = 3000 if name == "peak_eq" else 10000
    audio = tone(frequency)
    processed = apply_effects(audio, 48000, [effect(name, gain_db=-6.0)])
    assert gain_db(audio, processed) < -4.0


@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("name", ["deesser", "peak_eq", "high_shelf"])
def test_new_effects_preserve_shape_silence_and_disabled_audio(name, channels):
    audio = tone(7000)
    if channels == 2:
        audio = np.stack([audio, audio * 0.5])
    processed = apply_effects(audio, 48000, [effect(name)])
    assert processed.shape == audio.shape
    assert processed.dtype == np.float32 and np.isfinite(processed).all()
    silence = apply_effects(np.zeros_like(audio), 48000, [effect(name)])
    assert silence.shape == audio.shape
    assert np.isfinite(silence).all()
    assert not silence.any()
    disabled = effect(name)
    disabled["enabled"] = False
    np.testing.assert_array_equal(apply_effects(audio, 48000, [disabled]), audio)


@pytest.mark.parametrize("params", [{"frequency_hz": -1}, {"ratio": 0}, {"unknown": 1}])
def test_deesser_still_rejects_invalid_parameters(params):
    assert validate_effects_chain([effect("deesser", **params)]) is not None


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audio_path = tmp_path / "original.wav"
    sf.write(audio_path, tone(200, sample_rate=24000) + tone(9000, 0.04, sample_rate=24000), 24000)
    with factory() as db:
        db.add(database.VoiceProfile(id="voice", name="Spanish narrator", language="es"))
        db.add(database.Generation(id="recording", profile_id="voice", text="Respira con calma.",
                                   audio_path="original.wav", status="completed"))
        db.add(database.ProfileSample(id="sample", profile_id="voice", audio_path="original.wav",
                                     reference_text="Respira con calma."))
        db.commit()

    def get_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(profiles.router)
    app.include_router(effects.router)
    app.dependency_overrides[database.get_db] = get_db
    with TestClient(app) as client:
        yield client, audio_path
    engine.dispose()


@pytest.mark.parametrize("name", SAVED_CHAINS)
def test_saved_mastering_chain_can_save_preview_and_create_a_version(api, name):
    client, source = api
    chain = SAVED_CHAINS[name]
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    available = client.get("/effects/available").json()["effects"]
    assert {"deesser", "peak_eq", "high_shelf"} <= {e["type"] for e in available}
    assert validate_effects_chain(chain) is None

    saved = client.put("/profiles/voice/effects", json={"effects_chain": chain})
    assert saved.status_code == 200, saved.text
    assert saved.json()["effects_chain"] == chain

    preview = client.post("/effects/preview/recording", json={"effects_chain": chain})
    assert preview.status_code == 200, preview.text
    audio, rate = sf.read(io.BytesIO(preview.content))
    assert rate == 24000 and len(audio) == 24000
    assert np.isfinite(audio).all() and np.any(audio)

    version = client.post("/generations/recording/versions/apply-effects", json={
        "effects_chain": chain, "label": name, "set_as_default": False,
    })
    assert version.status_code == 200, version.text
    assert version.json()["effects_chain"] == chain
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_reference_audition_uses_draft_effects_without_overwriting_original(api):
    client, source = api
    original_bytes = source.read_bytes()
    original, _ = sf.read(source)
    rendered = []
    for chain in [[], [effect("gain", gain_db=-12.0)],
                  [{**effect("gain", gain_db=-12.0), "enabled": False}]]:
        response = client.post("/effects/preview/sample/sample", json={"effects_chain": chain})
        assert response.status_code == 200, response.text
        audio, rate = sf.read(io.BytesIO(response.content))
        assert rate == 24000 and audio.shape == original.shape
        assert "no-store" in response.headers["cache-control"]
        rendered.append(audio)
    assert abs(gain_db(original, rendered[1]) + 12.0) < 0.02
    np.testing.assert_array_equal(original, rendered[0])
    np.testing.assert_array_equal(original, rendered[2])
    assert source.read_bytes() == original_bytes
    assert client.get("/profiles/voice").json()["effects_chain"] is None
    assert client.get("/generations/recording/versions").json() == []


def test_reference_audition_rejects_missing_samples_and_invalid_chains(api):
    client, _ = api
    assert client.post("/effects/preview/sample/missing", json={"effects_chain": []}).status_code == 404
    response = client.post("/effects/preview/sample/sample", json={"effects_chain": [effect("unknown")]})
    assert response.status_code == 400
