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
        created = await profiles.create_profile(models.VoiceProfileCreate(name='Laura', language='es', default_engine='minimax', default_speed=0.8, default_pitch=-2, default_emotion='calm'), db)
        updated = await profiles.update_profile(created.id, models.VoiceProfileCreate(name='Laura', language='es', description='Updated description'), db)
        assert (updated.default_speed, updated.default_pitch, updated.default_emotion) == (0.8, -2, 'calm')
        updated = await profiles.update_profile(created.id, models.VoiceProfileCreate(name='Laura', language='es', default_speed=1, default_pitch=0, default_emotion=None), db)
        assert (updated.default_speed, updated.default_pitch, updated.default_emotion) == (1, 0, None)
        db.expire_all()
        saved = db.query(database.VoiceProfile).filter_by(id=created.id).one()
        assert (saved.default_speed, saved.default_pitch, saved.default_emotion) == (1, 0, None)
    sql.dispose()
