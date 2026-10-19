"""Change a supplied voice while retaining its recorded delivery.

No synthesis, text edits, inserted pauses, compression or speed changes.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard, PitchShift
from scipy.signal import correlate, correlation_lags

from refine_podcast_audio import estimate_true_peak


def vary(source, output, semitones=-0.55, character="warm"):
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    if not len(audio) or not np.all(np.isfinite(audio)):
        raise ValueError("Invalid source audio")
    if character not in ("warm", "narrator"):
        raise ValueError("Unknown voice character")
    limit = 1 if character == "warm" else 4
    if not -limit <= semitones <= limit:
        raise ValueError(f"This voice character accepts at most {limit} semitones")
    # Pad the processor boundaries, then retain exactly the original frames.
    padding = rate
    padded = np.pad(audio.T, ((0, 0), (padding, padding)))
    eq = ([LowShelfFilter(cutoff_frequency_hz=160, gain_db=1.0),
           PeakFilter(cutoff_frequency_hz=750, gain_db=-1.5, q=0.7),
           PeakFilter(cutoff_frequency_hz=2600, gain_db=0.8, q=0.7),
           HighShelfFilter(cutoff_frequency_hz=6500, gain_db=-0.6)]
          if character == "narrator" else
          [LowShelfFilter(cutoff_frequency_hz=170, gain_db=0.6),
           HighShelfFilter(cutoff_frequency_hz=5500, gain_db=-0.8)])
    board = Pedalboard([PitchShift(semitones=semitones), *eq])
    processed = board(padded, rate)[:, padding:padding + len(audio)]
    source_rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
    output_rms = np.sqrt(np.mean(processed.astype(np.float64) ** 2))
    if min(source_rms, output_rms) < 1e-8:
        raise ValueError("No useful signal")
    true_peak = estimate_true_peak(processed, rate)
    gain = min(source_rms / output_rms, 10 ** (-1.5 / 20) / true_peak)
    processed *= gain
    if processed.shape != audio.T.shape or not np.all(np.isfinite(processed)):
        raise RuntimeError("Output must retain the source frame count and channels")

    # Check that the processing has not delayed the recording's energy envelope.
    hop = max(1, round(rate * 0.005))
    def envelope(signal):
        mono = np.mean(signal, axis=0)
        count = len(mono) // hop * hop
        return np.sqrt(np.mean(mono[:count].reshape(-1, hop) ** 2, axis=1))
    before, after = envelope(audio.T), envelope(processed)
    scores = correlate(after - after.mean(), before - before.mean())
    lags = correlation_lags(len(after), len(before))
    region = np.abs(lags * hop / rate) <= 0.1
    lag = int(lags[region][np.argmax(scores[region])])
    if abs(lag * hop / rate) > 0.01:
        raise RuntimeError("Processing introduced an unexpected timing offset")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, processed.T, rate, subtype="PCM_24")
    report = {
        "source": str(Path(source).resolve()), "output": str(output.resolve()),
        "frames": len(audio), "duration_sec": len(audio) / rate,
        "sample_rate": rate, "channels": audio.shape[1],
        "pitch_shift_semitones": semitones,
        "character": character,
        "eq": ([{"type": "low_shelf", "hz": 160, "db": 1.0},
                {"type": "peak", "hz": 750, "db": -1.5, "q": 0.7},
                {"type": "peak", "hz": 2600, "db": 0.8, "q": 0.7},
                {"type": "high_shelf", "hz": 6500, "db": -0.6}]
               if character == "narrator" else
               [{"type": "low_shelf", "hz": 170, "db": 0.6},
                {"type": "high_shelf", "hz": 5500, "db": -0.8}]),
        "gain_db": float(20 * np.log10(gain)),
        "estimated_true_peak_dbfs_4x": float(20 * np.log10(true_peak * gain)),
        "energy_envelope_lag_ms": lag * hop / rate * 1000,
        "energy_envelope_correlation": float(np.corrcoef(before, after)[0, 1]),
        "speed_change": False, "inserted_pauses": False,
        "synthesis": False, "subjective_listening_review": "pending",
    }
    output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semitones", type=float, default=-0.55)
    parser.add_argument("--character", choices=["warm", "narrator"], default="warm")
    args = parser.parse_args()
    vary(args.source, args.output, args.semitones, args.character)
