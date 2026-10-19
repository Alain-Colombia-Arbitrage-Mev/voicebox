"""A selected reference must never silently become a generic speaker."""
from types import SimpleNamespace

import pytest

from backend.backends.mlx_backend import MLXTTSBackend


def loaded_backend(model):
    backend = MLXTTSBackend()
    backend.model = model
    backend._current_model_size = backend.model_size
    return backend


@pytest.mark.asyncio
async def test_missing_selected_reference_does_not_synthesize(tmp_path):
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError('Synthesis must not start with a missing reference')

    backend = loaded_backend(SimpleNamespace(generate=generate))
    with pytest.raises(FileNotFoundError, match='Voice reference audio is missing'):
        await backend.generate('Hola.', {'ref_audio': str(tmp_path / 'deleted.wav')}, language='es')
    assert calls == []


@pytest.mark.asyncio
async def test_clone_failure_does_not_retry_with_generic_voice(tmp_path):
    reference = tmp_path / 'reference.wav'
    reference.write_bytes(b'reference supplied to mock model')
    calls = []

    def generate(text, ref_audio=None, ref_text='', lang_code='auto'):
        calls.append({'ref_audio': ref_audio, 'lang_code': lang_code})
        raise RuntimeError('Reference encoder failed')

    backend = loaded_backend(SimpleNamespace(generate=generate))
    with pytest.raises(RuntimeError, match='Reference encoder failed'):
        await backend.generate('Hola.', {'ref_audio': str(reference), 'ref_text': 'Hola.'}, language='es')
    assert calls == [{'ref_audio': str(reference), 'lang_code': 'spanish'}]


@pytest.mark.asyncio
async def test_incompatible_model_does_not_ignore_selected_reference(tmp_path):
    reference = tmp_path / 'reference.wav'
    reference.write_bytes(b'reference supplied to mock model')
    calls = []

    def generate(text, lang_code='auto'):
        calls.append(text)
        raise AssertionError('A model without reference support must not synthesize')

    backend = loaded_backend(SimpleNamespace(generate=generate))
    with pytest.raises(RuntimeError, match='cannot use the requested voice reference'):
        await backend.generate('Hola.', {'ref_audio': str(reference)}, language='es')
    assert calls == []
