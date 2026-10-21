"""Moving a voice or recording between libraries preserves its provider and delivery."""
import io
import json
import zipfile

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import config, database, models
from backend.services import export_import, history, profiles


@pytest.mark.asyncio
async def test_voice_and_recording_archive_preserve_minimax_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_data_dir', tmp_path)
    sql = create_engine(f"sqlite:///{tmp_path / 'archive.db'}")
    database.Base.metadata.create_all(sql)
    reference = tmp_path / 'reference.wav'
    sf.write(reference, 0.2 * np.sin(np.arange(24000 * 12) * 0.04), 24000)
    with sessionmaker(bind=sql)() as db:
        original = await profiles.create_profile(models.VoiceProfileCreate(name='Laura', language='es', default_engine='minimax', default_speed=0.91, default_pitch=0, default_emotion=None, personality='Narradora serena.', minimax_clone_options={'need_noise_reduction': True, 'need_volume_normalization': True}), db)
        await profiles.add_profile_sample(original.id, str(reference), 'Universo, hoy me presento ante ti.', db)
        stored = db.query(database.VoiceProfile).filter_by(id=original.id).one()
        stored.effects_chain = json.dumps([{'type': 'reverb', 'enabled': True, 'params': {'wet_level': 0.1}}])
        db.commit()
        archive = export_import.export_profile_to_zip(original.id, db)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            payload = json.loads(zipped.read('manifest.json'))['profile']
            assert not any(key in payload for key in ['api_key', 'minimax_voice_id', 'preset_voice_id'])
        restored = await export_import.import_profile_from_zip(archive, db)
        assert restored.name == 'Laura (1)'
        assert (restored.default_engine, restored.default_speed, restored.default_pitch, restored.default_emotion) == ('minimax', 0.91, 0, None)
        assert restored.language == 'es' and restored.personality == 'Narradora serena.'
        assert restored.minimax_clone_options.model_dump() == {'need_noise_reduction': True, 'need_volume_normalization': True}
        assert restored.effects_chain[0].type == 'reverb'
        first = await profiles.get_profile_samples(original.id, db)
        second = await profiles.get_profile_samples(restored.id, db)
        assert first[0].reference_text == second[0].reference_text
        a, sr = sf.read(config.resolve_storage_path(first[0].audio_path))
        b, rate = sf.read(config.resolve_storage_path(second[0].audio_path))
        assert sr == rate
        np.testing.assert_allclose(a, b, atol=1 / 32768)
        recording = await history.create_generation(original.id, 'Universo, hoy me presento ante ti.', 'es', str(reference), 12, None, db, engine='minimax', speed=0.91, pitch=0, emotion=None)
        exported = export_import.export_generation_to_zip(recording.id, db)
        imported = await export_import.import_generation_from_zip(exported, db)
        saved = db.query(database.Generation).filter_by(id=imported['id']).one()
        assert (saved.engine, saved.speed, saved.pitch, saved.emotion, saved.language) == ('minimax', 0.91, 0, None, 'es')
    sql.dispose()


@pytest.mark.asyncio
async def test_old_profile_archive_still_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_data_dir', tmp_path)
    sql = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    database.Base.metadata.create_all(sql)
    wav = io.BytesIO()
    sf.write(wav, np.sin(np.arange(24000 * 12) * 0.04) * 0.2, 24000, format='WAV')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as zipped:
        zipped.writestr('manifest.json', json.dumps({'version':'1.0', 'profile':{'name':'Old voice', 'language':'es'}}))
        zipped.writestr('samples.json', json.dumps({'ref.wav':'Una voz anterior.'}))
        zipped.writestr('samples/ref.wav', wav.getvalue())
    with sessionmaker(bind=sql)() as db:
        restored = await export_import.import_profile_from_zip(data.getvalue(), db)
        assert restored.language == 'es' and restored.default_speed is None
    sql.dispose()
