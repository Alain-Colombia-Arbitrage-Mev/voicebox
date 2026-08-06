"""
Prosody capture for voice profiles.

Analyzes a profile's reference audio to estimate how the speaker delivers
speech — speaking rate, pitch movement, energy — and maps that onto the
per-generation prosody controls (emotion, speed) so generations default to
the same delivery as the reference sample.

The estimates are intentionally conservative: the cloned voice already
carries timbre and accent, so this layer only captures *delivery*. When the
signal is ambiguous the emotion is left unset (engine auto).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Spanish/English conversational speech averages ~6.2 syllables/second.
# The reference rate maps to a 1.0x speed multiplier.
BASELINE_SYLLABLES_PER_SEC = 6.2

# Vowel clusters approximate syllables well enough for es/en rate estimation.
_VOWEL_GROUP_RE = re.compile(r"[aeiouáéíóúüàèìòùâêîôû]+", re.IGNORECASE)


@dataclass
class ProsodyAnalysis:
    """Result of analyzing one reference sample."""

    speed: float  # engine speed multiplier [0.6, 1.4]
    emotion: Optional[str]  # MiniMax emotion value or None (auto)
    pitch: int  # semitone shift — always 0, the clone carries timbre
    # Raw metrics, returned for transparency/debugging
    syllables_per_sec: float
    f0_median_hz: float
    f0_std_semitones: float
    energy_cv: float
    voiced_duration_sec: float
    # Production character: reverb tail measured after speech offsets.
    # 0.0 = dry studio booth; >0.25s suggests audible room/echo treatment.
    reverb_tail_sec: float = 0.0
    # Suggested effects chain reproducing the measured room (empty = dry)
    effects_chain: list = None  # type: ignore[assignment]


def count_syllables(text: str) -> int:
    """Approximate syllable count via vowel groups (works for es/en)."""
    return max(1, len(_VOWEL_GROUP_RE.findall(text)))


def analyze_sample(audio_path: str, reference_text: str) -> ProsodyAnalysis:
    """Estimate delivery prosody from a reference recording.

    Speed comes from syllable rate against a conversational baseline.
    Emotion is inferred from rate + pitch variability + energy variability
    with conservative thresholds; ambiguous samples return None (auto).
    """
    import librosa

    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    # Trim leading/trailing silence so pauses at the edges don't dilute rate
    y_trimmed, _ = librosa.effects.trim(y, top_db=30)
    if len(y_trimmed) < sr // 2:
        y_trimmed = y

    duration = len(y_trimmed) / sr

    # Voiced-only duration: drop internal silences so a contemplative
    # recording with long pauses doesn't read as ultra-slow articulation.
    intervals = librosa.effects.split(y_trimmed, top_db=35)
    voiced_duration = float(sum((end - start) for start, end in intervals)) / sr
    if voiced_duration < 0.5:
        voiced_duration = duration

    syllables = count_syllables(reference_text)
    syl_per_sec = syllables / voiced_duration

    # Pause ratio: how much of the take is silence — meditative speech
    # carries long gaps that syllable rate over voiced time can't see.
    pause_ratio = 1.0 - (voiced_duration / duration) if duration > 0 else 0.0

    # Pitch statistics (fundamental frequency)
    f0, voiced_flag, _ = librosa.pyin(
        y_trimmed,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
    )
    f0_voiced = f0[~np.isnan(f0)] if f0 is not None else np.array([])
    if len(f0_voiced) > 10:
        f0_median = float(np.median(f0_voiced))
        # Std in semitones is speaker-independent, unlike Hz
        f0_semitones = 12 * np.log2(f0_voiced / f0_median)
        f0_std_st = float(np.std(f0_semitones))
    else:
        f0_median = 0.0
        f0_std_st = 0.0

    # Energy variability (coefficient of variation of RMS)
    rms = librosa.feature.rms(y=y_trimmed)[0]
    energy_cv = float(np.std(rms) / np.mean(rms)) if np.mean(rms) > 0 else 0.0

    rate_ratio = syl_per_sec / BASELINE_SYLLABLES_PER_SEC
    speed = round(float(np.clip(rate_ratio, 0.6, 1.4)), 2)

    emotion = _infer_emotion(rate_ratio, pause_ratio, f0_std_st, energy_cv)

    reverb_tail = _estimate_reverb_tail(y_trimmed, sr, intervals)

    return ProsodyAnalysis(
        speed=speed,
        emotion=emotion,
        pitch=0,
        syllables_per_sec=round(syl_per_sec, 2),
        f0_median_hz=round(f0_median, 1),
        f0_std_semitones=round(f0_std_st, 2),
        energy_cv=round(energy_cv, 2),
        voiced_duration_sec=round(voiced_duration, 2),
        reverb_tail_sec=round(reverb_tail, 3),
        effects_chain=_effects_for_tail(reverb_tail),
    )


def _estimate_reverb_tail(y: np.ndarray, sr: int, intervals: np.ndarray) -> float:
    """Median time for energy to decay 20 dB after speech offsets.

    Studio processing (reverb/echo) shows up as long tails after each
    phrase; a dry booth recording decays almost instantly. Only offsets
    followed by a real gap (>0.4 s) are measured so coarticulation
    doesn't pollute the estimate.
    """
    import librosa

    if len(intervals) == 0:
        return 0.0

    frame = 512
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=frame)[0]
    times = np.arange(len(rms)) * frame / sr

    tails: list[float] = []
    for idx, (start, end) in enumerate(intervals):
        gap_end = intervals[idx + 1][0] / sr if idx + 1 < len(intervals) else len(y) / sr
        offset_t = end / sr
        if gap_end - offset_t < 0.4:
            continue

        mask = (times >= offset_t) & (times < gap_end)
        seg = rms[mask]
        if len(seg) < 3 or seg[0] <= 0:
            continue
        target = seg[0] * 10 ** (-20 / 20)  # -20 dB from the offset level
        below = np.where(seg <= target)[0]
        if len(below) > 0:
            tails.append(float(below[0]) * frame / sr)
        else:
            tails.append(float(gap_end - offset_t))

    return float(np.median(tails)) if tails else 0.0


def _effects_for_tail(tail_sec: float) -> list:
    """Map a measured reverb tail onto a matching pedalboard chain."""
    if tail_sec < 0.25:
        return []  # dry recording — no effects to reproduce
    room_size = float(np.clip(tail_sec / 1.2, 0.2, 0.9))
    wet = float(np.clip(0.15 + tail_sec * 0.25, 0.15, 0.5))
    chain = [
        {
            "type": "reverb",
            "enabled": True,
            "params": {
                "room_size": round(room_size, 2),
                "damping": 0.5,
                "wet_level": round(wet, 2),
                "dry_level": 0.6,
                "width": 1.0,
            },
        }
    ]
    # A very long tail usually means a distinct echo on top of the room
    if tail_sec > 0.8:
        chain.append(
            {
                "type": "delay",
                "enabled": True,
                "params": {"delay_seconds": 0.25, "feedback": 0.25, "mix": 0.2},
            }
        )
    return chain


def _infer_emotion(
    rate_ratio: float,
    pause_ratio: float,
    f0_std_st: float,
    energy_cv: float,
) -> Optional[str]:
    """Map acoustic delivery onto a MiniMax emotion, or None when ambiguous.

    Thresholds are deliberately wide — a wrong emotion is worse than auto.
    """
    # Slow, gap-heavy, pitch-flat delivery → contemplative/meditative
    if (rate_ratio < 0.95 or pause_ratio > 0.35) and f0_std_st < 3.0:
        return "calm"
    # Slow, flat AND energetically dull → subdued
    if rate_ratio < 0.8 and f0_std_st < 2.0 and energy_cv < 0.45:
        return "sad"
    # Fast with lively pitch movement → upbeat
    if rate_ratio > 1.15 and f0_std_st > 3.5:
        return "happy"
    return None
