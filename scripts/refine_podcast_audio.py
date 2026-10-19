"""Adjust a supplied recording locally, preserving speaker, text and timing.

Example: python scripts/refine_podcast_audio.py INPUT.mp3 --output OUTPUT.wav
This is equalization/dynamics processing; it performs no voice cloning or upload.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import Pedalboard, HighpassFilter, LowShelfFilter, PeakFilter, HighShelfFilter, Compressor


def estimate_true_peak(audio, rate):
    """Four-times oversampled peak, using bounded overlapping blocks."""
    from scipy.signal import resample_poly

    peak = 0.0
    block = rate * 10
    for start in range(0, audio.shape[1], block):
        end = min(start + block, audio.shape[1])
        lo = max(0, start - 64)
        hi = min(audio.shape[1], end + 64)
        oversampled = resample_poly(audio[:, lo:hi], 4, 1, axis=1)
        useful = oversampled[:, 4 * (start - lo):4 * (end - lo)]
        peak = max(peak, float(np.max(np.abs(useful))))
    return peak


def refine(source, output, preset="warm"):
    if preset not in ("warm", "asmr", "motivational"):
        raise ValueError("Unknown audio preset")
    audio, rate = sf.read(source, dtype='float32', always_2d=True)
    if not len(audio) or not np.all(np.isfinite(audio)):
        raise ValueError('Source audio is empty or invalid')
    board = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=55),
        LowShelfFilter(cutoff_frequency_hz=140, gain_db=-0.8),
        PeakFilter(cutoff_frequency_hz=280, gain_db=-1.2, q=0.7),
        PeakFilter(cutoff_frequency_hz=2200, gain_db=0.8, q=0.7),
        HighShelfFilter(cutoff_frequency_hz=7000, gain_db=-0.7),
        Compressor(threshold_db=-23, ratio=1.4, attack_ms=25, release_ms=200),
    ] if preset == "motivational" else [
        HighpassFilter(cutoff_frequency_hz=80),
        LowShelfFilter(cutoff_frequency_hz=160, gain_db=0.8),
        PeakFilter(cutoff_frequency_hz=300, gain_db=-1.5, q=0.7),
        PeakFilter(cutoff_frequency_hz=7000, gain_db=-2.0, q=1.0),
        HighShelfFilter(cutoff_frequency_hz=6000, gain_db=-2.5),
        Compressor(threshold_db=-28, ratio=1.3, attack_ms=30, release_ms=250),
    ] if preset == "asmr" else [
        HighpassFilter(cutoff_frequency_hz=65),
        LowShelfFilter(cutoff_frequency_hz=180, gain_db=1.2),
        PeakFilter(cutoff_frequency_hz=320, gain_db=-1.2, q=0.7),
        HighShelfFilter(cutoff_frequency_hz=6500, gain_db=-1.3),
        Compressor(threshold_db=-24, ratio=1.7, attack_ms=25, release_ms=150),
    ])
    processed = board(audio.T.copy(), rate)
    rms = float(np.sqrt(np.mean(processed.astype(np.float64)**2)))
    if rms < 1e-8:
        raise ValueError('Source contains no useful signal')
    peak_ceiling_db = -3.0 if preset == "asmr" else (-1.5 if preset == "motivational" else -1.0)
    target_rms_db = -24.0 if preset == "asmr" else (-18.5 if preset == "motivational" else -19.0)
    oversampled_peak = estimate_true_peak(processed, rate) if preset == "motivational" else None
    controlled_peak = oversampled_peak if oversampled_peak is not None else float(np.max(np.abs(processed)))
    peak_headroom_db = peak_ceiling_db - 20*np.log10(controlled_peak)
    gain_db = min(6.0, target_rms_db - 20*np.log10(rms), peak_headroom_db)
    processed *= 10**(gain_db/20)
    processed = processed[:, :len(audio)]
    if processed.shape[1] != len(audio) or not np.all(np.isfinite(processed)):
        raise RuntimeError('Processing did not preserve the original duration')
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, processed.T, rate, subtype='PCM_24')
    report = {
        'source': str(Path(source).resolve()), 'output': str(output.resolve()),
        'duration_sec':len(audio)/rate, 'sample_rate':rate, 'channels':audio.shape[1],
        'peak':float(np.max(np.abs(processed))),
        'rms_dbfs':float(20*np.log10(np.sqrt(np.mean(processed.astype(np.float64)**2)))),
        'gain_db':float(gain_db), 'preset':preset, 'processing':'gentle EQ, light compression and controlled gain',
        'target_rms_dbfs':target_rms_db, 'peak_ceiling_dbfs':peak_ceiling_db,
        'pitch_shift':False, 'time_stretch':False, 'voice_cloning':False,
        'subjective_listening_review':'pending',
    }
    if oversampled_peak is not None:
        report['estimated_true_peak_dbfs_4x'] = float(20*np.log10(oversampled_peak) + gain_db)
    output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='source'},ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preset',choices=['warm','asmr'],default='warm')
    args=parser.parse_args();refine(args.source,args.output,args.preset)
