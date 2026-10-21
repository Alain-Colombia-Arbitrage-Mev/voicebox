"""Saving voice metadata must preserve delivery, including explicit neutral values."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import config, database, models
from backend.services import profiles


@pytest.mark.asyncio
async def test_saved_delivery_can_be_inherited_reset_or_cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_data_dir', tmp_path)
    sql = create_engine(f"sqlite:///{tmp_path / 'profile.db'}")
    database.Base.metadata.create_all(sql)
    with sessionmaker(bind=sql)() as db:
        created = await profiles.create_profile(models.VoiceProfileCreate(name='Laura', language='es', default_engine='minimax', default_speed=0.8, default_pitch=-2, default_emotion='calm', minimax_clone_options={'need_noise_reduction': True}), db)
        updated = await profiles.update_profile(created.id, models.VoiceProfileCreate(name='Laura', language='es', description='Updated description'), db)
        assert (updated.default_speed, updated.default_pitch, updated.default_emotion) == (0.8, -2, 'calm')
        assert updated.minimax_clone_options.need_noise_reduction is True
        updated = await profiles.update_profile(created.id, models.VoiceProfileCreate(name='Laura', language='es', default_speed=1, default_pitch=0, default_emotion=None), db)
        assert (updated.default_speed, updated.default_pitch, updated.default_emotion) == (1, 0, None)
        db.expire_all()
        saved = db.query(database.VoiceProfile).filter_by(id=created.id).one()
        assert (saved.default_speed, saved.default_pitch, saved.default_emotion) == (1, 0, None)
    sql.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('engine', ['minimax', 'qwen'])
async def test_saved_cleanup_is_forwarded_only_to_minimax(tmp_path, monkeypatch, engine):
    from unittest.mock import AsyncMock
    from backend import backends
    monkeypatch.setattr(config, '_data_dir', tmp_path)
    sql = create_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
    database.Base.metadata.create_all(sql)
    options = {'need_noise_reduction': True, 'need_volume_normalization': True}
    voice = type('Backend', (), {'create_voice_prompt': AsyncMock(return_value=({'voice': 'selected'}, True))})()
    monkeypatch.setattr(backends, 'get_tts_backend_for_engine', lambda name: voice)
    with sessionmaker(bind=sql)() as db:
        created = await profiles.create_profile(models.VoiceProfileCreate(name='Laura', language='es', default_engine='minimax', minimax_clone_options=options), db)
        db.add(database.ProfileSample(profile_id=created.id, audio_path='reference.wav', reference_text='Hola.'))
        db.commit()
        await profiles.create_voice_prompt_for_profile(created.id, db, engine=engine)
        assert voice.create_voice_prompt.call_args.kwargs == {'use_cache': True, **({'clone_options':options} if engine == 'minimax' else {})}
    sql.dispose()
