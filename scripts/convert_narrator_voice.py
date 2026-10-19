"""Convert recorded delivery to a reference speaker with Seed-VC.

Run with the isolated Seed-VC runtime. Model code is kept under ignored
data/tools/seed-vc, with its upstream revision in SOURCE.json. This uses
source F0 conditioning, zero semitone shift and unchanged speaking rate.
"""
import argparse
import json
import os
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace

import numpy as np
import soundfile as sf


def convert(source, target, output, model_source, steps=35, seed=42):
    source, target, output, model_source = [
        Path(p).resolve() for p in (source, target, output, model_source)
    ]
    for path in (source, target, model_source / "inference.py"):
        if not path.is_file():
            raise FileNotFoundError(path)
    if source == output or target == output:
        raise ValueError("Keep the source and reference recordings intact")
    output.parent.mkdir(parents=True, exist_ok=True)
    original, rate = sf.read(source, dtype="float32", always_2d=True)
    if not len(original) or not np.isfinite(original).all():
        raise ValueError("Invalid source recording")

    # Initialize HF's shared cache before upstream inference sets its defaults.
    import huggingface_hub
    from huggingface_hub import constants
    os.environ["VOICEBOX_VC_MODEL_CACHE"] = constants.HF_HUB_CACHE
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    sys.path.insert(0, str(model_source))
    import torch
    import inference

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(6)

    # torchaudio 2.11 save requires a separate codec runtime. Write the actual
    # model output directly as PCM instead, without codec conversion.
    raw_path = output.with_name(output.stem + "-raw.wav")
    def save_pcm(_path, waveform, sample_rate):
        sf.write(raw_path, waveform.detach().cpu().numpy().T,
                 sample_rate, subtype="PCM_24")
    inference.torchaudio.save = save_pcm
    args = SimpleNamespace(
        source=str(source), target=str(target), output=str(output.parent),
        diffusion_steps=steps, length_adjust=1.0, inference_cfg_rate=0.7,
        f0_condition=True, auto_f0_adjust=False, semi_tone_shift=0,
        checkpoint=None, config=None, fp16=False,
    )
    started = time.monotonic()
    inference.main(args)
    converted, converted_rate = sf.read(raw_path, dtype="float32", always_2d=True)
    if converted_rate != rate:
        import librosa
        converted = librosa.resample(converted.T, orig_sr=converted_rate,
                                    target_sr=rate).T
    delta = len(converted) - len(original)
    if abs(delta / rate) > 0.05:
        raise RuntimeError("Model output duration differs by more than 50 ms")
    # Mel frames quantize the last few milliseconds. Retain the source length
    # without time stretching or changing any internal pauses.
    if delta < 0:
        converted = np.pad(converted, ((0, -delta), (0, 0)))
    converted = converted[:len(original)]
    if not np.isfinite(converted).all() or np.max(np.abs(converted)) < 1e-5:
        raise RuntimeError("Invalid converted audio")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from refine_podcast_audio import estimate_true_peak
    peak = estimate_true_peak(converted.T, rate)
    source_rms = float(np.sqrt(np.mean(original.astype(np.float64) ** 2)))
    converted_rms = float(np.sqrt(np.mean(converted.astype(np.float64) ** 2)))
    gain = min(source_rms / converted_rms, 10 ** (-1.5 / 20) / peak)
    converted *= gain
    sf.write(output, converted, rate, subtype="PCM_24")
    report = {
        "source": str(source), "target_speaker_reference": str(target),
        "output": str(output), "method": "Seed-VC speech-to-speech",
        "model_source": json.loads((model_source / "SOURCE.json").read_text()),
        "source_pitch_conditioning": True, "pitch_shift_semitones": 0,
        "automatic_pitch_adjustment": False, "length_adjust": 1.0,
        "diffusion_steps": steps, "seed": seed,
        "source_frames": len(original), "output_frames": len(converted),
        "sample_rate": rate, "duration_sec": len(original) / rate,
        "raw_duration_difference_ms": delta / rate * 1000,
        "gain_db": float(20 * np.log10(gain)),
        "source_rms_dbfs": float(20 * np.log10(source_rms)),
        "output_rms_dbfs": float(20 * np.log10(converted_rms * gain)),
        "estimated_true_peak_dbfs_4x": float(20 * np.log10(peak * gain)),
        "elapsed_seconds": time.monotonic() - started,
        "listening_review": "pending",
    }
    output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-source", type=Path, default=Path("data/tools/seed-vc"))
    parser.add_argument("--steps", type=int, default=35)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    convert(args.source, args.target, args.output, args.model_source, args.steps, args.seed)
