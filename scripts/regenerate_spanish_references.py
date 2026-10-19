"""Regenerate Mantralia scripts using the user's Spanish audio references.

Consumes MiniMax API credit. References are uploaded for voice cloning;
no text-only voice design is used. Jobs and voice provenance are persisted.
"""
import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx
import librosa
import soundfile as sf
from dotenv import load_dotenv
from faster_whisper import WhisperModel

from backend import config, database
from backend.backends.minimax_backend import MiniMaxTTSBackend
from scripts.refine_podcast_audio import refine
from scripts.save_audio_to_library import save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/regeneracion-referencias-es'


class ReferenceBackend(MiniMaxTTSBackend):
    """Build the delivery prompt from decoded samples, avoiding PyAV mismatch."""

    def __init__(self, slug):
        super().__init__()
        self.slug = slug

    async def _build_clone_prompt_slice(self, audio_path):
        target = OUT / (self.slug + '-delivery.wav')
        metadata = target.with_suffix('.json')
        if metadata.exists() and target.exists():
            return str(target), json.loads(metadata.read_text())['text']
        audio, rate = sf.read(audio_path, dtype='float32')
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        audio = audio[:round(rate * 7.3)]
        sf.write(target, audio, rate, subtype='PCM_16')
        model = WhisperModel('base', device='cpu', compute_type='int8', cpu_threads=6)
        segments, _ = model.transcribe(
            librosa.resample(audio, orig_sr=rate, target_sr=16000),
            language='es', beam_size=5, vad_filter=True,
            condition_on_previous_text=False,
        )
        text = ' '.join(segment.text.strip() for segment in segments)
        if not text:
            raise RuntimeError('Delivery reference could not be transcribed')
        metadata.write_text(json.dumps({'text': text, 'source': audio_path}, ensure_ascii=False, indent=2) + '\n')
        return str(target), text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://127.0.0.1:17493')
    parser.add_argument('--engine', choices=['minimax', 'qwen'], default='minimax')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    config.set_data_dir(ROOT / 'data')
    database.init_db()
    OUT.mkdir(parents=True, exist_ok=True)
    local_model = None
    retired = json.loads((ROOT / 'docs/mantralia/voces-retiradas.json').read_text())
    old = {g['id']: g['text'] for g in retired['generations']}
    references = [
        {'slug': 'argentina', 'name': 'Mantralia · Referencia Argentina · Narración',
         'pattern': 'Argentina-2026-10-08-00-35-*.mp3',
         'reference_text': '¿Ya imaginaste ese momento? El contrato firmado. La confirmación. El mensaje que dice vamos adelante. Pero pasan los días y la espera empieza a ocuparlo todo. Revisas el teléfono, repasas la conversación y te preguntas qué pudiste hacer diferente. Antes de volver a revisar, dedica unos minutos a reconocer cómo te está afectando esa espera.',
         'jobs': [('argentina-narracion', 'Mantralia · Regeneración desde Argentina · Narración', old['a94b8543-01fd-4597-97fa-58dfbcae02f1']),
                  ('voz-amiga', 'Mantralia · Regeneración desde Argentina · Voz Amiga', old['7d9212b8-b485-44ee-a6db-a6c19d253435']),
                  ('podcast-intencion', 'Mantralia · Regeneración desde Argentina · Intención', old['ed07d395-9d33-4351-b211-8234a96649d0']),
                  ('podcast-claridad', 'Mantralia · Regeneración desde Argentina · Claridad', old['eded7da6-b8db-4e17-bdb0-ff53b1aa0f48'])]},
        {'slug': 'laura', 'name': 'Mantralia · Referencia Laura · Calma',
         'pattern': 'laura-meditA-2026-10-08-00-38-*.mp3',
         'reference_text': 'Los recursos son ilimitados para nuestra creación. El universo anhela mi éxito. Los contratos se cierran con facilidad. Somos vasijas. Nos gusta contener. El dinero llega con facilidad. El dinero abunda en nuestra existencia.',
         'jobs': [('laura-calma', 'Mantralia · Regeneración desde Laura · Calma', old['bce93c85-4089-43c1-bdae-870e93045191'])]},
    ]
    with httpx.Client(base_url=args.server, timeout=180) as client:
        for reference in references:
            slug = reference['slug']
            source = next(Path('/Users/alainherrera/Downloads').glob(reference['pattern']))
            r = client.get('/profiles'); r.raise_for_status()
            profile = next((p for p in r.json() if p['name'] == reference['name']), None)
            if profile is None:
                r = client.post('/profiles', json={
                    'name': reference['name'], 'description':
                    'Voz regenerada desde el archivo de referencia en español aportado por el usuario: ' + source.name + '. Acento pendiente de valoración auditiva.',
                    'language': 'es', 'voice_type': 'cloned', 'default_engine': args.engine,
                }); r.raise_for_status(); profile = r.json()
            r = client.get(f"/profiles/{profile['id']}/samples"); r.raise_for_status()
            samples = r.json()
            if not samples:
                audio, rate = sf.read(source, dtype='float32')
                if audio.ndim == 2:
                    audio = audio.mean(axis=1)
                # Voicebox references are limited to thirty seconds.
                if slug == 'argentina':
                    audio = audio[:round(rate * 24.4)]
                reference_wav = OUT / (slug + '-reference.wav')
                sf.write(reference_wav, audio, rate, subtype='PCM_16')
                with reference_wav.open('rb') as file:
                    r = client.post(f"/profiles/{profile['id']}/samples",
                                    files={'file': (reference_wav.name, file, 'audio/wav')},
                                    data={'reference_text': reference['reference_text']})
                r.raise_for_status(); samples = [r.json()]
            path = config.resolve_storage_path(samples[0]['audio_path'])
            provenance = {'profile_id': profile['id'], 'source': str(source),
                          'method': 'audio_reference_clone', 'engine': args.engine,
                          'language': 'es', 'accent_review': 'pending_user_listening'}
            if args.engine == 'minimax':
                backend = ReferenceBackend(slug)
                prompt, cached = asyncio.run(backend.create_voice_prompt(str(path), reference['reference_text']))
                provenance['voice_id'] = prompt['minimax_voice_id']
            elif local_model is None:
                os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['TRANSFORMERS_OFFLINE'] = '1'
                from mlx_audio.tts.utils import load_model
                model_root = Path.home() / '.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-1.7B-Base-bf16/snapshots'
                model_path = next(model_root.iterdir())
                print('Loading cached local Qwen3-TTS model', flush=True)
                local_model = load_model(str(model_path))
            (OUT / (slug + '-reference.json')).write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
            db = next(database.get_db())
            try:
                row = db.query(database.VoiceProfile).filter_by(id=profile['id']).one()
                row.default_engine = args.engine
                row.default_emotion = 'calm'; row.default_speed = 0.96 if slug == 'laura' else 1.0
                row.default_pitch = 0; db.commit()
            finally:
                db.close()
            for job_slug, title, text in reference['jobs']:
                # Keep complete phrases together so the model receives their context.
                text = re.sub(r'\s*<#\d+(?:\.\d+)?#>\s*', ' ', text).strip()
                text = text.replace('(breath)', '').strip()
                job_file = OUT / (job_slug + '-job.json')
                raw = OUT / (job_slug + '-raw.wav')
                master = OUT / (job_slug + '.wav')
                if not raw.exists():
                    if args.engine == 'qwen':
                        import numpy as np
                        import mlx.core as mx
                        from backend.services.history import create_generation

                        mx.random.seed(21)
                        print(title + ': local generation', flush=True)
                        chunks = []
                        for result in local_model.generate(
                            text, ref_audio=str(path), ref_text=reference['reference_text'],
                            lang_code='Spanish', temperature=0.6, top_p=0.9,
                            max_tokens=4096, verbose=False,
                        ):
                            chunks.append(np.asarray(result.audio, dtype=np.float32))
                            rate = result.sample_rate
                        if not chunks:
                            raise RuntimeError('Local reference generation returned no audio')
                        audio = np.concatenate(chunks)
                        if not np.all(np.isfinite(audio)):
                            raise RuntimeError('Local generation contains invalid samples')
                        sf.write(raw, audio, rate, subtype='PCM_24')
                        db = next(database.get_db())
                        try:
                            generated = asyncio.run(create_generation(
                                profile_id=profile['id'], text=text, language='es',
                                audio_path=config.to_storage_path(raw), duration=len(audio)/rate,
                                seed=21, db=db, engine='qwen', model_size='1.7B', status='completed',
                            ))
                        finally:
                            db.close()
                        (OUT / (job_slug + '-local-job.json')).write_text(json.dumps({
                            'id': generated.id, 'profile_id': profile['id'], 'text': text,
                            'engine': 'qwen', 'reference_used': str(path),
                            'voice_reference_fallback': False,
                        }, ensure_ascii=False, indent=2) + '\n')
                    elif job_file.exists():
                        job = json.loads(job_file.read_text())
                    else:
                        r = client.post('/generate', json={
                            'profile_id': profile['id'], 'engine': 'minimax', 'language': 'es',
                            'text': text, 'emotion': 'calm', 'speed': 0.96 if slug == 'laura' else 1.0,
                            'pitch': 0, 'normalize': False, 'personality': False, 'crossfade_ms': 0,
                        }); r.raise_for_status(); job = r.json()
                        job_file.write_text(json.dumps({'id': job['id'], 'profile_id': profile['id'], 'text': text}, ensure_ascii=False, indent=2) + '\n')
                    if args.engine == 'minimax':
                        print(title + ': ' + job['id'], flush=True)
                        for _ in range(180):
                            r = client.get('/history/' + job['id']); r.raise_for_status(); job = r.json()
                            if job['status'] == 'failed':
                                raise RuntimeError('Generation failed: ' + job['id'])
                            if job['status'] == 'completed':
                                break
                            time.sleep(2)
                        else:
                            raise RuntimeError('Still processing; check persisted job before retry')
                        r = client.get('/library/' + job['id'] + '/audio'); r.raise_for_status()
                        raw.write_bytes(r.content)
                if not master.exists():
                    refine(raw, master, 'asmr' if slug == 'laura' else 'warm')
                save(master, title, args.server)


if __name__ == '__main__':
    main()
