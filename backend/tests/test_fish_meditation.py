"""Cloud contract, secret handling, durable clones and exact listening pauses."""

import json

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import database, models
from backend.backends import get_model_config, get_tts_backend_for_engine
from backend.backends.fish_backend import FishTTSBackend, FISH_SAMPLE_RATE
from backend.routes.settings import router
from backend.utils.chunked_tts import generate_chunked
from backend.utils.directed_speech import render_with_pauses


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()
    monkeypatch.setattr(database, "get_db", get_db)
    yield get_db
    engine.dispose()


def mock_cloud(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
async def test_fish_pcm_contract_and_exact_pause(monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers['model'] == 's2.1-pro'
        assert request.headers['authorization'] == 'Bearer test-secret'
        return httpx.Response(200, content=np.array([0, 16384, -16384], dtype='<i2').tobytes())
    mock_cloud(monkeypatch, handler)
    backend = FishTTSBackend()
    monkeypatch.setattr(backend, '_get_settings', lambda: {'api_key': 'test-secret', 'model': 's2.1-pro'})
    audio, rate = await backend.generate('Inhala. <#2#> Exhala.', {'preset_voice_id': 'native-latina'},
                                         instruct='warm [native Colombian]', emotion='calm', speed=0.9)
    assert rate == FISH_SAMPLE_RATE
    assert audio.dtype == np.float32
    assert len(audio) == 6 + 2 * rate
    np.testing.assert_array_equal(audio[3:-3], np.zeros(2 * rate))
    np.testing.assert_allclose(audio[:3], [0, 0.5, -0.5])
    assert all('<#' not in r['text'] and r['format'] == 'pcm' for r in requests)
    assert requests[0]['text'] == '[warm native Colombian] [calm] Inhala.'
    assert requests[0]['prosody']['speed'] == 0.9
    assert requests[0]['normalize'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 402, 429, 500])
async def test_provider_errors_do_not_echo_secrets(monkeypatch, status):
    mock_cloud(monkeypatch, lambda req: httpx.Response(status, json={'message': 'test-secret'}))
    backend = FishTTSBackend()
    monkeypatch.setattr(backend, '_get_settings', lambda: {'api_key': 'test-secret', 'model': 's2-pro'})
    with pytest.raises(RuntimeError, match=f'HTTP {status}') as error:
        await backend.generate('Hola.', {'fish_voice_id': 'voice'})
    assert 'test-secret' not in str(error.value)


@pytest.mark.asyncio
async def test_clone_is_private_persistent_and_account_scoped(db, tmp_path, monkeypatch):
    sample = tmp_path / 'voice.wav'
    sample.write_bytes(b'audio-reference')
    requests = []
    def handler(request):
        requests.append(request)
        assert b'name="visibility"\r\n\r\nprivate' in request.content
        assert b'name="voices"' in request.content
        return httpx.Response(200, json={'_id': f'voice-{len(requests)}'})
    mock_cloud(monkeypatch, handler)
    settings = {'api_key': 'account-one', 'model': 's2-pro'}
    monkeypatch.setattr(FishTTSBackend, '_get_settings', lambda self: settings)
    prompt, cached = await FishTTSBackend().create_voice_prompt(str(sample), 'Respira.')
    assert not cached
    again, cached = await FishTTSBackend().create_voice_prompt(str(sample), 'Respira.')
    assert cached and again == prompt and len(requests) == 1
    settings['api_key'] = 'account-two'
    other, cached = await FishTTSBackend().create_voice_prompt(str(sample), 'Respira.')
    assert not cached and other != prompt and len(requests) == 2


def test_settings_roundtrip_hides_secret_and_validates_model(db, monkeypatch):
    monkeypatch.delenv('FISH_AUDIO_API_KEY', raising=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database.get_db] = db
    # Route dependency was bound at import time; override that original too.
    from backend.routes import settings
    app.dependency_overrides[settings.get_db] = db
    client = TestClient(app)
    response = client.put('/settings/fish', json={'api_key': 'private-key', 'model': 's2.1-pro'})
    assert response.status_code == 200
    assert response.json() == {'api_key_set': True, 'model': 's2.1-pro'}
    assert 'private-key' not in client.get('/settings/fish').text
    assert client.put('/settings/fish', json={'model': 'invented-model'}).status_code == 422
    assert client.put('/settings/fish', json={'api_key': ''}).json()['api_key_set'] is False


@pytest.mark.asyncio
async def test_pause_does_not_crossfade_or_repeat_first_phrase():
    calls = []
    class Backend:
        async def generate(self, text, *args, **kwargs):
            calls.append(text)
            assert '<#' not in text
            return np.ones(10, dtype=np.float32), 100
    audio, rate = await generate_chunked(Backend(), '<#1#> Uno. <#2.25#> Uno. <#0.5#>', {}, crossfade_ms=500)
    assert calls == ['Uno.', 'Uno.']
    assert len(audio) == 100 + 10 + 225 + 10 + 50
    assert rate == 100
    assert np.all(audio[110:335] == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['Hola <#31#>', 'Hola <#0#>', '<#2#>', 'Hola' + '<#30#>' * 21,
                                'Hola <#-1#>', 'Hola <#1.234#>', 'Hola <#dos#>'])
async def test_invalid_pause_fails_before_paid_synthesis(text):
    calls = []
    async def generate(phrase):
        calls.append(phrase)
        return np.ones(10), 100
    with pytest.raises(ValueError):
        await render_with_pauses(text, generate, 100)
    assert calls == []


@pytest.mark.asyncio
async def test_malformed_pause_fails_before_chunked_provider_call():
    class Backend:
        async def generate(self, *args, **kwargs):
            pytest.fail('Invalid pause reached paid provider')
    with pytest.raises(ValueError, match='pause markers'):
        await generate_chunked(Backend(), 'Hola <#dos#>', {})


def test_minimax_environment_key_is_reported_without_full_secret(monkeypatch):
    from types import SimpleNamespace
    from backend.routes.settings import _minimax_response
    monkeypatch.setenv('MINIMAX_API_KEY', 'private-environment-secret')
    response = _minimax_response(SimpleNamespace(api_key=None, group_id=None,
                                               api_host='https://api.minimax.io', model='speech-2.8-hd'))
    assert response.api_key_set
    assert 'private-environment-secret' not in response.model_dump_json()


@pytest.mark.asyncio
async def test_sample_rate_change_is_rejected():
    async def generate(phrase):
        return np.ones(10), 24000
    with pytest.raises(RuntimeError, match='sample rate'):
        await render_with_pauses('Hola.', generate, 44100)


def test_registry_and_request_accept_fish():
    assert get_model_config('fish-speech').is_remote
    assert isinstance(get_tts_backend_for_engine('fish'), FishTTSBackend)
    assert models.GenerationRequest(profile_id='p1', text='Hola.', engine='fish', language='es').engine == 'fish'
