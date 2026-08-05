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

    return ProsodyAnalysis(
        speed=speed,
        emotion=emotion,
        pitch=0,
        syllables_per_sec=round(syl_per_sec, 2),
        f0_median_hz=round(f0_median, 1),
        f0_std_semitones=round(f0_std_st, 2),
        energy_cv=round(energy_cv, 2),
        voiced_duration_sec=round(voiced_duration, 2),
    )


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
