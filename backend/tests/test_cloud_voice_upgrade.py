"""Cloud voice defaults and exact pauses survive the 0.6 orchestration update."""
import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import backends, config, database, models
from backend.routes import generations
from backend.services import generation


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["minimax", "fish"])
async def test_saved_cloud_voice_generates_with_its_prosody_and_pauses(tmp_path, monkeypatch, engine):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    sql = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    database.Base.metadata.create_all(sql)
    factory = sessionmaker(bind=sql)

    def get_db():
        with factory() as session:
            yield session

    calls = []

    class Voice:
        PROSODY_PARAMS = ("emotion", "speed", "pitch")

        def is_loaded(self):
            return True

        async def create_voice_prompt(self, path, text, use_cache=True):
            assert path == str(tmp_path / "reference.wav")
            return {"selected_speaker": "warm-variant"}, True

        async def generate(self, text, prompt, language="en", seed=None, instruct=None, **kwargs):
            assert prompt == {"selected_speaker": "warm-variant"}
            calls.append((text, {**kwargs, "language": language}))
            return np.full(100, 0.2, dtype=np.float32), 1000

    async def load(*args, **kwargs):
        pass

    queued = []
    monkeypatch.setattr(generations, "enqueue_generation", lambda gid, coro: queued.append(coro))
    monkeypatch.setattr(generation, "get_db", get_db)
    monkeypatch.setattr(generation, "release_generation_memory", lambda model: None)
    monkeypatch.setattr(backends, "get_tts_backend_for_engine", lambda name: Voice())
    monkeypatch.setattr(backends, "load_engine_model", load)
    try:
        with factory() as db:
            db.add(database.VoiceProfile(id="voice", name="Warm Spanish variant", language="es",
                voice_type="cloned", default_engine=engine, default_emotion="calm",
                default_speed=0.95, default_pitch=0))
            db.add(database.ProfileSample(id="sample", profile_id="voice", audio_path="reference.wav",
                reference_text="Hay deseos que llevas tiempo sintiendo."))
            db.commit()
            request = models.GenerationRequest(profile_id="voice", text="Pregunta. <#0.25#> Responde.",
                                               language="es", normalize=False)
            result = await generations.generate_speech(request, db)
            assert request.engine is None
        assert len(queued) == 1
        await queued[0]
        with factory() as db:
            saved = db.query(database.Generation).filter_by(id=result.id).one()
            assert saved.status == "completed", saved.error
            assert saved.engine == engine
            assert (saved.emotion, saved.speed, saved.pitch) == ("calm", 0.95, 0)
            audio, rate = sf.read(config.resolve_storage_path(saved.audio_path))
            assert rate == 1000
            assert len(audio) == 450
            np.testing.assert_array_equal(audio[100:350], np.zeros(250))
        assert [text for text, _ in calls] == ["Pregunta.", "Responde."]
        assert all(kwargs["language"] == "es" and kwargs["speed"] == 0.95 and
                   kwargs["emotion"] == "calm" and kwargs["pitch"] == 0 for _, kwargs in calls)
    finally:
        sql.dispose()
