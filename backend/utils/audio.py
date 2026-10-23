"""
Audio processing utilities.
"""

import numpy as np
import soundfile as sf
import librosa
from typing import Tuple, Optional


def normalize_audio(
    audio: np.ndarray,
    target_db: float = -20.0,
    peak_limit: float = 0.85,
) -> np.ndarray:
    """
    Normalize audio to target loudness with peak limiting.
    
    Args:
        audio: Input audio array
        target_db: Target RMS level in dB
        peak_limit: Peak limit (0.0-1.0)
        
    Returns:
        Normalized audio array
    """
    # Convert to float32
    audio = audio.astype(np.float32)
    
    # Calculate current RMS
    rms = np.sqrt(np.mean(audio**2))
    
    # Calculate target RMS
    target_rms = 10**(target_db / 20)
    
    # Apply gain
    if rms > 0:
        gain = target_rms / rms
        audio = audio * gain
    
    # Peak limiting
    audio = np.clip(audio, -peak_limit, peak_limit)
    
    return audio


# Spoken-word delivery targets: -16 LUFS is the mono podcast convention,
# and a -1 dBFS ceiling leaves room for lossy encoders to overshoot.
DEFAULT_TARGET_LUFS = -16.0
DEFAULT_CEILING_DB = -1.0

# ITU-R BS.1770 integrates over 400 ms blocks; shorter material has no
# measurable integrated loudness.
_MIN_LOUDNESS_SECONDS = 0.4


def normalize_loudness(
    audio: np.ndarray,
    sample_rate: int,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    ceiling_db: float = DEFAULT_CEILING_DB,
) -> np.ndarray:
    """Normalize to an integrated-loudness target, then guarantee headroom.

    Loudness (ITU-R BS.1770) is what a listener actually perceives, so two
    takes normalized this way sit at the same level even when one is breathy
    and full of held silence and the other is not. RMS normalization cannot
    do that: silence drags the average down, and a meditation script is
    mostly silence.

    Peaks above *ceiling_db* are limited, not scaled away. Scaling the whole
    file by its single worst transient would cost several dB of loudness to
    one plosive; the limiter spends that reduction only where the peak is,
    so the take still lands on target.

    Args:
        audio: Input audio array (mono, float).
        sample_rate: Sample rate in Hz.
        target_lufs: Integrated loudness target in LUFS.
        ceiling_db: Peak ceiling in dBFS.

    Returns:
        Normalized audio array.
    """
    import pyloudnorm

    audio = audio.astype(np.float32)

    # Too short to measure, or pure silence: nothing meaningful to match.
    if len(audio) < _MIN_LOUDNESS_SECONDS * sample_rate:
        return normalize_audio(audio)
    if not np.any(audio):
        return audio

    meter = pyloudnorm.Meter(sample_rate)
    loudness = meter.integrated_loudness(audio)
    if not np.isfinite(loudness):
        return audio

    audio = audio * (10 ** ((target_lufs - loudness) / 20))

    ceiling = 10 ** (ceiling_db / 20)
    if float(np.max(np.abs(audio))) > ceiling:
        audio = limit_peaks(audio, sample_rate, ceiling)

    return audio.astype(np.float32)


# Look-ahead and recovery for the peak limiter. 5 ms is long enough to ride
# a plosive down before it arrives without audibly ducking the word.
_LIMITER_LOOKAHEAD_SECONDS = 0.005
_LIMITER_RELEASE_SECONDS = 0.05


def limit_peaks(audio: np.ndarray, sample_rate: int, ceiling: float) -> np.ndarray:
    """Hold *audio* under *ceiling* by ducking only around the peaks.

    Deliberately not pedalboard's ``Limiter``: that one applies makeup gain
    up to its threshold, which is a loudness maximizer and would undo a
    loudness target. This computes a gain envelope that is 1.0 everywhere
    the signal already fits, so the integrated loudness barely moves.

    Args:
        audio: Input audio array (mono, float).
        sample_rate: Sample rate in Hz.
        ceiling: Peak ceiling as a linear amplitude (not dB).

    Returns:
        Audio whose absolute peak is at most *ceiling*.
    """
    from scipy.ndimage import minimum_filter1d
    from scipy.signal import fftconvolve

    envelope = np.abs(audio)
    required = np.minimum(1.0, ceiling / np.maximum(envelope, 1e-9)).astype(np.float32)

    # Widen each reduction to cover look-ahead plus recovery, so the gain is
    # already down when the peak lands and comes back up gradually after it.
    span = int((_LIMITER_LOOKAHEAD_SECONDS + _LIMITER_RELEASE_SECONDS) * sample_rate)
    window = max(3, (2 * span + 1) | 1)
    gain = minimum_filter1d(required, size=window, mode="nearest")

    # Round off the corners of that envelope; a rectangular gain step is what
    # would be audible as distortion. The kernel is kept strictly narrower
    # than the minimum window, which is what guarantees the smoothed gain can
    # never rise back above what any peak in reach requires.
    kernel_size = max(3, min(span, window // 2 - 1) | 1)
    kernel = np.hanning(kernel_size + 2)[1:-1]
    kernel = kernel / kernel.sum()
    # Edge-pad first: "same" convolution tapers toward the array bounds,
    # which would fade the first and last tens of milliseconds of every
    # limited take. Padding with the edge value keeps those samples flat.
    pad = kernel_size // 2
    padded = np.pad(gain, pad, mode="edge")
    # FFT convolution: a direct one at this kernel length costs tens of
    # seconds on a five-minute take.
    gain = fftconvolve(padded, kernel, mode="same")[pad : pad + len(audio)].astype(np.float32)

    return np.clip(audio * gain, -ceiling, ceiling)


# Room tone. A real microphone records its room everywhere, including under
# the speech, so the bed is continuous rather than patched into the gaps:
# no seams to click, and the inter-word micro-gaps get a floor too.
ROOM_TONE_LEVEL_DB = -60.0
_ROOM_TONE_FADE_SECONDS = 0.03
# Width of the smoothing kernel on the noise. Unfiltered white noise reads
# as hiss; taking the top off makes it read as a room.
_ROOM_TONE_SMOOTHING = 16


def add_room_tone(
    audio: np.ndarray,
    sample_rate: int,
    level_db: float = ROOM_TONE_LEVEL_DB,
) -> np.ndarray:
    """Lay a continuous noise floor under the take.

    A synthesized pause is samples of exactly zero. Cutting from voice to
    absolute nothing and back is the most recognisably synthetic thing in a
    spoken recording, and a meditation script is mostly pause — so it is
    also the most audible. At -60 dBFS the bed is inaudible as sound and
    audible only as the absence of a hole.

    Args:
        audio: Input audio array (mono, float).
        sample_rate: Sample rate in Hz.
        level_db: RMS level of the bed in dBFS.

    Returns:
        Audio of the same length with a noise floor under it.
    """
    audio = audio.astype(np.float32)
    if len(audio) < 2:
        return audio

    rng = np.random.default_rng(0)
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    kernel = np.ones(_ROOM_TONE_SMOOTHING, dtype=np.float32) / _ROOM_TONE_SMOOTHING
    noise = np.convolve(noise, kernel, mode="same").astype(np.float32)

    rms = float(np.sqrt(np.mean(noise**2)))
    if rms == 0:
        return audio
    noise *= (10 ** (level_db / 20)) / rms

    # Ease the floor in and out so the file does not begin on a step.
    fade_n = min(int(_ROOM_TONE_FADE_SECONDS * sample_rate), len(noise) // 2)
    if fade_n > 0:
        ramp = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
        noise[:fade_n] *= ramp
        noise[-fade_n:] *= ramp[::-1]

    return audio + noise


def measure_loudness(audio: np.ndarray, sample_rate: int) -> Optional[float]:
    """Integrated loudness in LUFS, or None when the clip is too short."""
    import pyloudnorm

    audio = audio.astype(np.float32)
    if len(audio) < _MIN_LOUDNESS_SECONDS * sample_rate or not np.any(audio):
        return None
    loudness = pyloudnorm.Meter(sample_rate).integrated_loudness(audio)
    return float(loudness) if np.isfinite(loudness) else None


def load_audio(
    path: str,
    sample_rate: int = 24000,
    mono: bool = True,
) -> Tuple[np.ndarray, int]:
    """
    Load audio file with normalization.
    
    Args:
        path: Path to audio file
        sample_rate: Target sample rate
        mono: Convert to mono
        
    Returns:
        Tuple of (audio_array, sample_rate)
    """
    audio, sr = librosa.load(path, sr=sample_rate, mono=mono)
    return audio, sr


def save_audio(
    audio: np.ndarray,
    path: str,
    sample_rate: int = 24000,
) -> None:
    """
    Save audio file with atomic write and error handling.

    Writes to a temporary file first, then atomically renames to the
    target path.  This prevents corrupted/partial WAV files if the
    process is interrupted mid-write.

    Args:
        audio: Audio array
        path: Output path
        sample_rate: Sample rate

    Raises:
        OSError: If file cannot be written
    """
    from pathlib import Path
    import os

    temp_path = f"{path}.tmp"
    try:
        # Ensure parent directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first (explicit format since .tmp
        # extension is not recognised by soundfile)
        sf.write(temp_path, audio, sample_rate, format='WAV')

        # Atomic rename to final path
        os.replace(temp_path, path)

    except Exception as e:
        # Clean up temp file on failure
        try:
            if Path(temp_path).exists():
                Path(temp_path).unlink()
        except Exception:
            pass  # Best effort cleanup

        raise OSError(f"Failed to save audio to {path}: {e}") from e


def has_tts_runaway(
    audio: np.ndarray,
    sample_rate: int = 24000,
    frame_ms: int = 20,
    silence_threshold_db: float = -40.0,
    max_internal_silence_ms: int = 2000,
) -> bool:
    """Detect speech followed by a long silence and then more output.

    This shape is a reliable signal that a TTS model missed EOS and resumed
    with hallucinated speech or codec noise. Leading and trailing silence do
    not count because they are not bounded by non-silent audio.
    """
    frame_len = int(sample_rate * frame_ms / 1000)
    if frame_len == 0 or len(audio) < frame_len:
        return False

    n_frames = len(audio) // frame_len
    threshold_linear = 10 ** (silence_threshold_db / 20)
    max_silence_frames = int(max_internal_silence_ms / frame_ms)
    seen_speech = False
    consecutive_silence = 0

    for i in range(n_frames):
        frame = audio[i * frame_len : (i + 1) * frame_len]
        is_speech = np.sqrt(np.mean(frame**2)) >= threshold_linear
        if is_speech:
            if seen_speech and consecutive_silence >= max_silence_frames:
                return True
            seen_speech = True
            consecutive_silence = 0
        elif seen_speech:
            consecutive_silence += 1

    return False


def trim_tts_output(
    audio: np.ndarray,
    sample_rate: int = 24000,
    frame_ms: int = 20,
    silence_threshold_db: float = -40.0,
    min_silence_ms: int = 200,
    max_internal_silence_ms: int = 1000,
    fade_ms: int = 30,
) -> np.ndarray:
    """
    Trim trailing silence and post-silence hallucination from TTS output.

    Chatterbox sometimes produces ``[speech][silence][hallucinated noise]``.
    This detects internal silence gaps longer than *max_internal_silence_ms*
    and cuts the audio at that boundary, then trims trailing silence and
    applies a short cosine fade-out.

    Args:
        audio: Input audio array (mono float32)
        sample_rate: Sample rate in Hz
        frame_ms: Frame size for RMS energy calculation
        silence_threshold_db: dB threshold below which a frame is silence
        min_silence_ms: Minimum trailing silence to keep
        max_internal_silence_ms: Cut after any silence gap longer than this
        fade_ms: Cosine fade-out duration in ms

    Returns:
        Trimmed audio array
    """
    frame_len = int(sample_rate * frame_ms / 1000)
    if frame_len == 0 or len(audio) < frame_len:
        return audio

    n_frames = len(audio) // frame_len
    threshold_linear = 10 ** (silence_threshold_db / 20)

    # Compute per-frame RMS
    rms = np.array(
        [
            np.sqrt(np.mean(audio[i * frame_len : (i + 1) * frame_len] ** 2))
            for i in range(n_frames)
        ]
    )
    is_speech = rms >= threshold_linear

    # Find first speech frame
    first_speech = 0
    for i, s in enumerate(is_speech):
        if s:
            first_speech = max(0, i - 1)  # keep 1 frame padding
            break

    # Walk forward from first speech; cut at long internal silence gaps
    max_silence_frames = int(max_internal_silence_ms / frame_ms)
    consecutive_silence = 0
    cut_frame = n_frames

    for i in range(first_speech, n_frames):
        if is_speech[i]:
            consecutive_silence = 0
        else:
            consecutive_silence += 1
            if consecutive_silence >= max_silence_frames:
                cut_frame = i - consecutive_silence + 1
                break

    # Trim trailing silence from the cut point
    min_silence_frames = int(min_silence_ms / frame_ms)
    end_frame = cut_frame
    while end_frame > first_speech and not is_speech[end_frame - 1]:
        end_frame -= 1
    # Keep a short tail
    end_frame = min(end_frame + min_silence_frames, cut_frame)

    # Convert frames back to samples
    start_sample = first_speech * frame_len
    end_sample = min(end_frame * frame_len, len(audio))

    trimmed = audio[start_sample:end_sample].copy()

    # Cosine fade-out
    fade_samples = int(sample_rate * fade_ms / 1000)
    if fade_samples > 0 and len(trimmed) > fade_samples:
        fade = np.cos(np.linspace(0, np.pi / 2, fade_samples)) ** 2
        trimmed[-fade_samples:] *= fade

    return trimmed


def preprocess_reference_audio(
    audio: np.ndarray,
    sample_rate: int,
    peak_target: float = 0.95,
    trim_top_db: float = 40.0,
    edge_padding_ms: int = 100,
) -> np.ndarray:
    """
    Clean up a reference-audio sample before validation/storage.

    Removes DC offset, trims leading/trailing silence, and caps the peak so a
    slightly-hot recording doesn't get rejected downstream as "clipping". The
    goal is to accept reasonable real-world recordings — not to repair badly
    distorted ones. True clipping artifacts inside the waveform can't be
    recovered by peak scaling and will still sound bad.

    Args:
        audio: Mono audio array.
        sample_rate: Sample rate of ``audio`` in Hz.
        peak_target: Peak amplitude cap in [0, 1]. Applied only if the input
            peak exceeds this value.
        trim_top_db: Silence threshold for edge trimming, in dB below peak.
            40 dB sits below normal speech dynamic range (≈30 dB) so soft
            trailing syllables are preserved, while still catching obvious
            leading/trailing silence. Lower values are more aggressive;
            librosa's own default is 60.
        edge_padding_ms: Milliseconds of padding to add back at each edge
            *only if* trimming shortened the waveform, so TTS engines have a
            brief silence to anchor on without ever making the output longer
            than the input.

    Returns:
        Preprocessed audio array (float32).
    """
    audio = audio.astype(np.float32, copy=False)

    if audio.size == 0:
        return audio

    audio = audio - float(np.mean(audio))

    trimmed, _ = librosa.effects.trim(audio, top_db=trim_top_db)
    if 0 < trimmed.size < audio.size:
        pad_each = int(sample_rate * edge_padding_ms / 1000)
        # Never pad past the original length — for near-max-duration uploads
        # an unconditional pad would push them over the 30 s ceiling and
        # trigger a spurious "too long" rejection.
        headroom = (audio.size - trimmed.size) // 2
        pad = min(pad_each, max(headroom, 0))
        if pad > 0:
            trimmed = np.pad(trimmed, (pad, pad), mode="constant")
        audio = trimmed

    peak = float(np.abs(audio).max())
    if peak > peak_target and peak > 0:
        audio = audio * (peak_target / peak)

    return audio


def validate_reference_audio(
    audio_path: str,
    min_duration: float = 2.0,
    max_duration: float = 30.0,
    min_rms: float = 0.01,
) -> Tuple[bool, Optional[str]]:
    """
    Validate reference audio for voice cloning.

    Args:
        audio_path: Path to audio file
        min_duration: Minimum duration in seconds
        max_duration: Maximum duration in seconds
        min_rms: Minimum RMS level

    Returns:
        Tuple of (is_valid, error_message)
    """
    result = validate_and_load_reference_audio(
        audio_path, min_duration, max_duration, min_rms
    )
    return (result[0], result[1])


def validate_and_load_reference_audio(
    audio_path: str,
    min_duration: float = 2.0,
    max_duration: float = 30.0,
    min_rms: float = 0.01,
) -> Tuple[bool, Optional[str], Optional[np.ndarray], Optional[int]]:
    """
    Validate and load reference audio in a single pass.

    Applies :func:`preprocess_reference_audio` before checks so that
    slightly-hot recordings aren't rejected as clipping. Duration and RMS
    checks run on the preprocessed waveform.

    Returns:
        Tuple of (is_valid, error_message, audio_array, sample_rate)
    """
    try:
        audio, sr = load_audio(audio_path)
        audio = preprocess_reference_audio(audio, sr)
        duration = len(audio) / sr

        if duration < min_duration:
            return False, f"Audio too short (minimum {min_duration} seconds)", None, None
        if duration > max_duration:
            return False, f"Audio too long (maximum {max_duration} seconds)", None, None

        rms = np.sqrt(np.mean(audio**2))
        if rms < min_rms:
            return False, "Audio is too quiet or silent", None, None

        return True, None, audio, sr
    except Exception as e:
        return False, f"Error validating audio: {str(e)}", None, None
