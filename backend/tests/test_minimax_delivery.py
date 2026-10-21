"""MiniMax account isolation, clone recovery and provider delivery contracts."""
from unittest.mock import AsyncMock

import httpx
import numpy as np
import pytest

from backend.backends import minimax_backend as module


@pytest.fixture
def backend(monkeypatch):
    instance = module.MiniMaxTTSBackend()
    settings = {"host": "https://api.minimax.io", "api_key": "test-key", "group_id": None, "model": "speech-2.8-hd"}
    monkeypatch.setattr(instance, "_get_settings", lambda: settings)
    registry, cache = {}, {}
    monkeypatch.setattr(instance, "_registry_lookup", registry.get)
    monkeypatch.setattr(instance, "_registry_save", lambda voice, sample: registry.update({sample: voice}))
    monkeypatch.setattr(instance, "_registry_delete", lambda voice: None)
    monkeypatch.setattr(instance, "_registry_touch", lambda voice: None)
    monkeypatch.setattr(module, "get_cached_voice_prompt", cache.get)
    monkeypatch.setattr(module, "cache_voice_prompt", lambda key, value: cache.update({key: dict(value)}))
    return instance, settings, registry, cache


def test_clone_cache_is_scoped_to_account_region_and_group(backend):
    instance, settings, *_ = backend
    original = instance._scoped_sample_hash(settings, "sample")
    for field, value in [("api_key", "other-key"), ("host", "https://api.minimaxi.com"), ("group_id", "another-group")]:
        assert instance._scoped_sample_hash(dict(settings, **{field: value}), "sample") != original


@pytest.mark.asyncio
async def test_clone_uploads_original_without_an_unverified_speech_prompt(backend, tmp_path, monkeypatch):
    instance, settings, *_ = backend
    sample = tmp_path / 'original.wav'
    sample.write_bytes(b'original recording')
    calls = []

    def respond(request):
        import json
        calls.append(request)
        if request.url.path == '/v1/files/upload':
            assert b'original recording' in request.content
            return httpx.Response(200, json={'file': {'file_id': 'fixture'}, 'base_resp': {'status_code': 0}})
        payload = json.loads(request.content)
        assert payload['file_id'] == 'fixture'
        assert 'clone_prompt' not in payload
        return httpx.Response(200, json={'base_resp': {'status_code': 0}})

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(respond)))
    await instance._clone_voice(settings, str(sample), 'A transcript without timestamps.')
    assert [r.url.path for r in calls] == ['/v1/files/upload', '/v1/voice_clone']


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True])
async def test_legacy_clone_is_reused_only_after_ownership_check(backend, tmp_path, monkeypatch, owned):
    instance, settings, registry, _ = backend
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"reference")
    registry[module.get_cache_key(str(sample), "texto")] = "old-clone"
    owns = AsyncMock(return_value=owned)
    clone = AsyncMock(return_value="new-clone")
    monkeypatch.setattr(instance, "_owns_voice", owns)
    monkeypatch.setattr(instance, "_clone_voice", clone)
    prompt, cached = await instance.create_voice_prompt(str(sample), "texto")
    assert cached is owned
    assert prompt["minimax_voice_id"] == ("old-clone" if owned else "new-clone")
    again, cached = await instance.create_voice_prompt(str(sample), "texto")
    assert cached and again == prompt
    assert owns.await_count == 1
    assert clone.await_count == (0 if owned else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [2042, 2054])
async def test_expired_clone_recovers_once_across_pause_segments(backend, monkeypatch, code):
    instance, *_ = backend
    seen = []

    async def speech(settings, voice, text, *args, **kwargs):
        seen.append(voice)
        if voice == "expired":
            raise module.MiniMaxAPIError(code, "unavailable")
        return np.ones(320, dtype=np.float32), 32000

    clone = AsyncMock(return_value="repaired")
    monkeypatch.setattr(instance, "_clone_voice", clone)
    monkeypatch.setattr(instance, "_generate_with_voice", speech)
    prompt = {"minimax_voice_id": "expired", "ref_audio": "original.wav", "ref_text": "original", "sample_hash": "scoped"}
    audio, rate = await instance.generate("Una frase. <#0.25#> Otra frase.", prompt, "es", speed=1, pitch=0)
    assert seen == ["expired", "repaired", "repaired"]
    assert clone.await_count == 1
    assert prompt["minimax_voice_id"] == "repaired"
    assert rate == 32000 and len(audio) == 8640
    assert not audio[320:8320].any()


@pytest.mark.asyncio
async def test_failed_repair_preserves_original_prompt(backend, monkeypatch):
    instance, _, registry, cache = backend
    registry["scoped"] = "expired"
    monkeypatch.setattr(instance, "_generate_with_voice", AsyncMock(side_effect=module.MiniMaxAPIError(2054, "missing")))
    monkeypatch.setattr(instance, "_clone_voice", AsyncMock(return_value="new-clone"))
    prompt = {"minimax_voice_id": "expired", "ref_audio": "original.wav", "sample_hash": "scoped"}
    with pytest.raises(module.MiniMaxAPIError):
        await instance.generate("Hola.", prompt)
    assert prompt["minimax_voice_id"] == registry["scoped"] == "expired"
    assert not cache


@pytest.mark.asyncio
@pytest.mark.parametrize("speed,pitch", [(1, 0), (0.8, -2), (1.25, 2)])
async def test_neutral_delivery_reaches_minimax_without_pitch_shaping(backend, monkeypatch, speed, pitch):
    instance, settings, *_ = backend
    sent = []

    def respond(request):
        import json
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"base_resp": {"status_code": 0}, "data": {"audio": "00000100"}})

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond)))
    await instance._generate_with_voice(settings, "clone", "¿Qué deseas?", "es", None, speed, pitch, is_clone=True)
    assert sent[0]["voice_setting"] == {"voice_id": "clone", "speed": speed, "pitch": pitch}
    assert sent[0]["language_boost"] == "Spanish"
    assert sent[0]["model"] == "speech-2.8-hd"
    assert "voice_modify" not in sent[0]


@pytest.mark.asyncio
async def test_keepalive_preserves_other_account_registry_rows(tmp_path, monkeypatch, backend):
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import database

    sql = create_engine(f"sqlite:///{tmp_path / 'voices.db'}")
    database.Base.metadata.create_all(sql)
    factory = sessionmaker(bind=sql)

    def get_db():
        with factory() as session:
            yield session

    with factory() as db:
        db.add_all([database.MiniMaxVoice(voice_id=voice, sample_hash=voice, last_used_at=datetime.utcnow() - timedelta(days=5)) for voice in ['owned', 'other-account']])
        db.commit()
    instance, *_ = backend
    speech = AsyncMock(return_value=(np.zeros(32), 32000))
    monkeypatch.setattr(database, 'get_db', get_db)
    monkeypatch.setattr(module, 'MiniMaxTTSBackend', lambda: instance)
    monkeypatch.setattr(instance, '_owned_voice_ids', AsyncMock(return_value={'owned'}))
    monkeypatch.setattr(instance, '_generate_with_voice', speech)
    await module.refresh_stale_voices()
    assert speech.await_count == 1
    assert speech.await_args.args[1] == 'owned'
    with factory() as db:
        assert db.query(database.MiniMaxVoice).count() == 2
    sql.dispose()
