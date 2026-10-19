"""Extend reviewed quiet gaps without removing or resynthesizing spoken audio."""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def retime(source, plan_path, output):
    audio, rate = sf.read(source, dtype='float32', always_2d=True)
    if not len(audio) or not np.all(np.isfinite(audio)):
        raise ValueError('Invalid source audio')
    plan=json.loads(Path(plan_path).read_text())
    cuts=[]; previous_end=0
    for pause in plan['pauses']:
        start=float(pause['gap_start']);end=float(pause['gap_end']);extra=float(pause['add_sec'])
        if not (previous_end <= start < end <= len(audio)/rate and 0 < extra <= 2):
            raise ValueError('Pause intervals must be ordered, nonoverlapping and within the recording')
        previous_end=end
        lo=int(start*rate);hi=int(end*rate);window=max(1,round(.02*rate))
        if hi-lo < window+2:
            raise ValueError('Reviewed quiet gap is too short')
        energy=np.mean(audio[lo:hi].astype(np.float64)**2,axis=1)
        rms=np.sqrt(np.convolve(energy,np.ones(window)/window,mode='valid'))
        index=int(np.argmin(rms));quiet_db=20*np.log10(float(rms[index])+1e-12)
        if quiet_db > -34:
            raise ValueError(f"Pause after {pause['after']} needs manual review: no sufficiently quiet gap")
        cut=lo+index+window//2
        cuts.append({'frame':cut,'add_frames':round(extra*rate),'after':pause['after'],'source_sec':cut/rate,'added_sec':extra,'quiet_dbfs':quiet_db})
    processed=audio.copy();fade=max(1,round(.002*rate))
    for cut in cuts:
        frame=cut['frame']
        processed[frame-fade:frame]*=np.linspace(1,0,fade,dtype=np.float32)[:,None]
        processed[frame:frame+fade]*=np.linspace(0,1,fade,dtype=np.float32)[:,None]
    pieces=[];cursor=0
    for cut in cuts:
        pieces.extend([processed[cursor:cut['frame']],np.zeros((cut['add_frames'],audio.shape[1]),dtype=np.float32)])
        cursor=cut['frame']
    pieces.append(processed[cursor:]);result=np.concatenate(pieces)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    sf.write(output,result,rate,subtype='PCM_24')
    report={'source_duration_sec':len(audio)/rate,'output_duration_sec':len(result)/rate,'sample_rate':rate,'spoken_audio_removed':False,'speech_resynthesized':False,'pitch_shift':False,'pauses':cuts,'listening_review':'pending'}
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(output),'duration_sec':len(result)/rate,'added_sec':sum(x['added_sec'] for x in cuts),'pauses':len(cuts)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();retime(args.source,args.plan,args.output)
