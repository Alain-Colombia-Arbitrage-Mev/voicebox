"""Create original voices from text descriptions, with no speaker reference.

By default creates podcast voices; --spec selects another original voice brief.

Consumes MiniMax API credit. Persists Voicebox profiles and completed recordings.
The supplied third-party recording is never read or uploaded by this script.
"""
import argparse
import json
import time
from pathlib import Path

import httpx
import soundfile as sf
from dotenv import load_dotenv

from backend.backends.minimax_backend import MiniMaxTTSBackend
from backend.utils.cache import get_cache_key
from backend import database
from backend import config

ROOT=Path(__file__).resolve().parents[1]
TEXT=('Hay deseos que llevas tiempo sintiendo, pero todavía no has puesto en palabras. '
      'Tal vez buscas una oportunidad, una conversación pendiente o una dirección que vuelva a ilusionarte. '
      'En Mantralia, puedes dedicar un momento a esa intención. Escribe tu petición al universo, '
      'elige un mandala para acompañarla y pregúntate: ¿qué paso está en mis manos? '
      'Abre Mantralia y empieza por expresar lo que deseas.')
PREVIEW='Hay deseos que llevas tiempo sintiendo, pero todavía no has puesto en palabras. Tal vez buscas una oportunidad o una dirección que vuelva a ilusionarte. ¿Qué paso está en tus manos hoy?'
VOICES=[
 ('narrador-cercano','Mantralia · Narrador original cercano',
  'Original adult male voice, native Colombian Spanish with a light Bogota accent. Clear light-medium tenor timbre, smooth and articulate, warm professional podcast presenter. Thoughtful conversational phrasing, quietly confident, engaged and welcoming. Natural medium pace, subtle persuasive emphasis, varied intonation. No gravelly texture, no whispering, no sleepy meditation delivery, no theatrical announcer tone.'),
 ('narradora-cercana','Mantralia · Narradora original cercana',
  'Original adult female voice, native Colombian Spanish with a soft Bogota accent. Clear full medium-register timbre, bright warmth and professional diction. Reflective editorial podcast presenter, assured and engaging, natural connected phrases, subtle persuasive emphasis, varied intonation and an inviting action-oriented ending. Natural medium pace. No breathy whispering, no sleepy meditation delivery, no exaggerated advertising tone.'),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default='http://127.0.0.1:17493')
    parser.add_argument('--spec',type=Path,help='Optional JSON brief for original voices, script and delivery')
    args=parser.parse_args();load_dotenv(ROOT/'.env')
    spec=json.loads(args.spec.read_text()) if args.spec else {}
    text=spec.get('text',TEXT);preview_text=spec.get('preview_text',PREVIEW)
    voices=spec.get('voices') or [{'slug':slug,'name':name,'prompt':prompt,'emotion':'fluent','speed':1.03} for slug,name,prompt in VOICES]
    out=ROOT/spec.get('output_dir','data/mantralia/referencia-podcast');out.mkdir(parents=True,exist_ok=True)
    (out/'guion-alternativas.txt').write_text(text+'\n')
    config.set_data_dir(ROOT/'data');database.init_db()
    backend=MiniMaxTTSBackend();settings=backend._get_settings()
    with httpx.Client(timeout=180) as client:
        profiles=client.get(args.server+'/profiles');profiles.raise_for_status()
        profiles=profiles.json()
        for voice in voices:
            slug,name,prompt=voice["slug"],voice["name"],voice["prompt"]
            emotion=voice.get("emotion","fluent");speed=voice.get("speed",1.03)
            meta_path=out/(slug+'-design.json')
            preview_path=out/(slug+'-referencia.mp3')
            if meta_path.exists():
                meta=json.loads(meta_path.read_text())
            else:
                r=client.post(backend._url(settings,'/v1/voice_design'),
                              headers=backend._headers(settings),json={'prompt':prompt,'preview_text':preview_text})
                r.raise_for_status();result=r.json()
                if result.get('base_resp',{}).get('status_code',0)!=0:
                    raise RuntimeError('MiniMax Voice Design failed; provider status '+str(result.get('base_resp',{}).get('status_code')))
                if not result.get('voice_id') or not result.get('trial_audio'):
                    raise RuntimeError('MiniMax returned no usable designed voice')
                preview_path.write_bytes(bytes.fromhex(result['trial_audio']))
                meta={'voice_id':result['voice_id'],'prompt':prompt,'reference_text':preview_text,'provenance':'Original text-based Voice Design; no third-party audio reference'}
                meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
            profile=next((p for p in profiles if p['name']==name),None)
            if profile is None:
                r=client.post(args.server+'/profiles',json={'name':name,'description':spec.get('description','Voz sintética original diseñada por texto para podcast reflexivo y promocional. Sin referencia de una persona real. Acento pendiente de escucha.'),'language':'es','voice_type':'cloned','default_engine':'minimax'})
                r.raise_for_status();profile=r.json()
            r=client.get(args.server+f"/profiles/{profile['id']}/samples");r.raise_for_status()
            if not r.json():
                with preview_path.open('rb') as sample:
                    r=client.post(args.server+f"/profiles/{profile['id']}/samples",files={'file':(preview_path.name,sample,'audio/mpeg')},data={'reference_text':preview_text})
                r.raise_for_status();sample=r.json()
                path=config.resolve_storage_path(sample['audio_path'])
                backend._registry_save(meta['voice_id'],get_cache_key(str(path),preview_text))
                db=next(database.get_db())
                try:
                    row=db.query(database.VoiceProfile).filter_by(id=profile['id']).one()
                    row.default_emotion=emotion;row.default_speed=speed;row.default_pitch=0;row.effects_chain=None;db.commit()
                finally:
                    db.close()

            meta['profile_id']=profile['id'];meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
            final_path=out/(slug+'.wav')
            if final_path.exists():
                print('Already saved '+str(final_path),flush=True);continue
            job_path=out/(slug+'-job.json')
            if job_path.exists():
                job={'id':json.loads(job_path.read_text())['generation_id']}
            else:
                r=client.post(args.server+'/generate',json={'profile_id':profile['id'],'text':text,'language':'es','engine':'minimax','emotion':emotion,'speed':speed,'pitch':0,'personality':False,'normalize':spec.get('normalize',True),'crossfade_ms':0})
                r.raise_for_status();job=r.json()
                job_path.write_text(json.dumps({'generation_id':job['id']})+'\n')
            print(name+': generation '+job['id'],flush=True)
            for _ in range(150):
                r=client.get(args.server+'/history/'+job['id']);r.raise_for_status();job=r.json()
                if job['status']=='failed':raise RuntimeError('Voicebox generation failed; inspect history '+job['id'])
                if job['status']=='completed':break
                time.sleep(2)
            else:raise RuntimeError('Still processing; inspect Voicebox history before retrying')
            r=client.get(args.server+'/library/'+job['id']+'/audio');r.raise_for_status();final_path.write_bytes(r.content)
            audio,rate=sf.read(final_path)
            final_path.with_suffix('.json').write_text(json.dumps({'generation_id':job['id'],'profile_id':profile['id'],'voice_id':meta['voice_id'],'duration_sec':len(audio)/rate,'sample_rate':rate,'listening_review':'pending','original_synthetic_voice':True},ensure_ascii=False,indent=2)+'\n')
            print('Saved '+str(final_path)+f' ({len(audio)/rate:.2f}s)',flush=True)


if __name__=='__main__':main()
