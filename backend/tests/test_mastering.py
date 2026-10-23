"""Tests for the mastering stage: de-essing, peak limiting and loudness.

The properties pinned here are the ones that make a set of takes sound like
one production rather than eight different recordings: every file lands on
the same perceived level, nothing clips, and the sibilance control acts on
the S without dulling the voice.
"""

import numpy as np
import pytest

from backend.utils.audio import (
    DEFAULT_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    limit_peaks,
    measure_loudness,
    normalize_loudness,
)
from backend.utils.effects import (
    BUILTIN_PRESETS,
    CUSTOM_EFFECTS,
    apply_effects,
    build_pedalboard,
    validate_effects_chain,
)

SR = 44100
CEILING = 10 ** (DEFAULT_CEILING_DB / 20)


def speech_like(seconds=6.0, level=0.18, seed=0):
    """Bursts separated by silence — the shape of a scripted meditation."""
    rng = np.random.default_rng(seed)
    audio = np.zeros(int(seconds * SR), dtype=np.float32)
    for start in range(0, len(audio) - SR, int(1.8 * SR)):
        n = int(1.0 * SR)
        audio[start : start + n] = (level * rng.standard_normal(n)).astype(np.float32)
    return audio


def sibilant_speech(seconds=6.0, seed=0):
    """A voice body with short sibilant bursts riding on top.

    White noise will not do here: its high band is as loud on average as it
    is at its peak, so a de-esser and a low-pass filter would score the
    same. Real sibilance is brief and much louder than the tone around it.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    body = sum(0.12 * np.sin(2 * np.pi * f * t) for f in (150.0, 300.0, 450.0))
    audio = body.astype(np.float32)

    burst_len = int(0.08 * SR)
    for start in range(int(0.4 * SR), len(audio) - burst_len, int(0.9 * SR)):
        burst = (0.5 * rng.standard_normal(burst_len)).astype(np.float32)
        # Push the burst energy up where sibilance lives.
        from pedalboard import HighpassFilter, Pedalboard

        burst = Pedalboard([HighpassFilter(5000.0)])(burst[np.newaxis, :], SR)[0]
        audio[start : start + burst_len] += burst * np.hanning(burst_len).astype(np.float32)

    return audio


def band_peak_db(audio, cutoff_hz=6500.0):
    from pedalboard import HighpassFilter, Pedalboard

    band = Pedalboard([HighpassFilter(cutoff_hz)])(audio[np.newaxis, :], SR)[0]
    return 20 * np.log10(max(float(np.abs(band).max()), 1e-9))


def band_rms_db(audio, cutoff_hz=6500.0):
    from pedalboard import HighpassFilter, Pedalboard

    band = Pedalboard([HighpassFilter(cutoff_hz)])(audio[np.newaxis, :], SR)[0]
    return 20 * np.log10(max(float(np.sqrt(np.mean(band**2))), 1e-9))


# ── loudness ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("level", [0.02, 0.18, 0.6])
def test_any_input_level_lands_on_target(level):
    out = normalize_loudness(speech_like(level=level), SR)
    assert measure_loudness(out, SR) == pytest.approx(DEFAULT_TARGET_LUFS, abs=0.5)


def test_takes_end_up_at_the_same_level_as_each_other():
    levels = [
        measure_loudness(normalize_loudness(speech_like(level=lvl, seed=i), SR), SR)
        for i, lvl in enumerate((0.02, 0.1, 0.35, 0.7))
    ]
    assert max(levels) - min(levels) < 1.0, "takes must not drift apart in level"


def test_custom_target_is_honoured():
    out = normalize_loudness(speech_like(), SR, target_lufs=-23.0)
    assert measure_loudness(out, SR) == pytest.approx(-23.0, abs=0.5)


def test_ceiling_is_never_exceeded():
    audio = speech_like(level=0.5)
    audio[SR] = 3.0  # a plosive well past full scale
    assert float(np.abs(normalize_loudness(audio, SR)).max()) <= CEILING + 1e-6


def test_clip_too_short_to_measure_falls_back_instead_of_raising():
    short = np.full(1000, 0.1, dtype=np.float32)
    out = normalize_loudness(short, SR)
    assert out.shape == short.shape and np.all(np.isfinite(out))


def test_silence_is_left_alone():
    silence = np.zeros(SR, dtype=np.float32)
    assert not np.any(normalize_loudness(silence, SR))


def test_measure_loudness_returns_none_for_unmeasurable_clips():
    assert measure_loudness(np.zeros(SR, dtype=np.float32), SR) is None
    assert measure_loudness(np.full(100, 0.1, dtype=np.float32), SR) is None


# ── peak limiting ────────────────────────────────────────────────────


def test_limiter_catches_the_peak():
    audio = speech_like(level=0.3)
    audio[SR] = 2.5
    assert float(np.abs(limit_peaks(audio, SR, CEILING)).max()) <= CEILING + 1e-6


def test_limiter_spends_its_reduction_only_on_the_peak():
    """A whole file must not lose level because of one transient."""
    # Level chosen so the material itself fits under the ceiling — only the
    # injected transient needs limiting.
    audio = speech_like(level=0.15)
    assert float(np.abs(audio).max()) < CEILING
    audio[SR] = 2.5
    limited = limit_peaks(audio, SR, CEILING)
    assert measure_loudness(limited, SR) == pytest.approx(measure_loudness(audio, SR), abs=0.3)
    untouched = float(np.mean(np.isclose(limited, audio, atol=1e-6)))
    assert untouched > 0.95, "limiting should be local, not a global gain change"


def test_limiter_leaves_material_that_already_fits():
    audio = speech_like(level=0.05)
    assert np.allclose(limit_peaks(audio, SR, CEILING), audio, atol=1e-6)


# ── de-esser ─────────────────────────────────────────────────────────


def _deesser(threshold_db=-38.0, ratio=5.0):
    return [
        {
            "type": "deesser",
            "enabled": True,
            "params": {"frequency_hz": 6500.0, "threshold_db": threshold_db, "ratio": ratio},
        }
    ]


def test_deesser_is_transparent_when_it_cannot_engage():
    audio = speech_like()
    out = apply_effects(audio, SR, _deesser(threshold_db=0.0, ratio=1.0))
    # The complementary band split must reconstruct the input exactly.
    assert np.allclose(out, audio, atol=1e-6)


def test_deesser_takes_the_peaks_not_the_tone():
    audio = normalize_loudness(sibilant_speech(), SR)
    out = apply_effects(audio, SR, _deesser())
    peak_change = band_peak_db(out) - band_peak_db(audio)
    rms_change = band_rms_db(out) - band_rms_db(audio)
    assert peak_change < -1.0, "sibilant peaks should come down"
    assert peak_change < rms_change, "peaks must come down further than the average"


def test_deesser_leaves_the_body_of_the_voice_alone():
    """What separates a de-esser from rolling the top off a voice."""
    from pedalboard import LowpassFilter, Pedalboard

    audio = normalize_loudness(sibilant_speech(), SR)
    out = apply_effects(audio, SR, _deesser())

    # Below 300 Hz is where the fundamental of a voice lives. What little
    # change reaches it is the high-pass filter's own rolloff, not processing.
    board = Pedalboard([LowpassFilter(300.0)])
    low_change = float(np.abs(board(out[np.newaxis, :], SR)[0] - board(audio[np.newaxis, :], SR)[0]).max())
    full_change = float(np.abs(out - audio).max())

    assert low_change < 0.05 * full_change, "the body of the voice must survive intact"


# ── chain plumbing ───────────────────────────────────────────────────


def test_custom_effects_run_in_chain_order():
    """The de-esser's threshold is absolute, so its position matters.

    Handling custom effects outside the chain — all plugins first, then the
    de-esser — would make these two chains identical. They must not be.
    """
    audio = normalize_loudness(sibilant_speech(), SR)
    down = {"type": "gain", "enabled": True, "params": {"gain_db": -40.0}}
    up = {"type": "gain", "enabled": True, "params": {"gain_db": 40.0}}

    # Attenuated first, the de-esser is far below its threshold and can do
    # nothing, so the round trip returns the input.
    silenced = apply_effects(audio, SR, [down, *_deesser(), up])
    # De-essed first, at full level, it engages.
    engaged = apply_effects(audio, SR, [*_deesser(), down, up])

    assert np.allclose(silenced, audio, atol=1e-3)
    assert band_peak_db(engaged) < band_peak_db(audio) - 1.0


def test_disabled_custom_effect_is_skipped():
    audio = speech_like()
    chain = _deesser(threshold_db=-60.0, ratio=20.0)
    chain[0]["enabled"] = False
    assert np.allclose(apply_effects(audio, SR, chain), audio, atol=1e-6)


def test_build_pedalboard_skips_effects_it_cannot_build():
    board = build_pedalboard(
        [*_deesser(), {"type": "gain", "enabled": True, "params": {"gain_db": 3.0}}]
    )
    assert len(board) == 1, "the de-esser has no plugin to build"
    assert "deesser" in CUSTOM_EFFECTS


# ── presets ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("preset", ["voice_master", "meditation_room"])
def test_mastering_presets_are_valid_and_finish_on_target(preset):
    chain = BUILTIN_PRESETS[preset]["effects_chain"]
    assert validate_effects_chain(chain) is None

    staged = normalize_loudness(speech_like(level=0.3), SR)
    out = normalize_loudness(apply_effects(staged, SR, chain), SR)

    assert measure_loudness(out, SR) == pytest.approx(DEFAULT_TARGET_LUFS, abs=1.0)
    assert float(np.abs(out).max()) <= CEILING + 1e-6
    assert out.shape == staged.shape


def test_mastering_preset_reduces_sibilance_on_a_normalized_take():
    staged = normalize_loudness(speech_like(level=0.3), SR)
    chain = BUILTIN_PRESETS["voice_master"]["effects_chain"]
    out = normalize_loudness(apply_effects(staged, SR, chain), SR)
    assert band_peak_db(out) < band_peak_db(staged)


# ── room tone ────────────────────────────────────────────────────────


def with_silence(seconds=6.0, seed=0):
    """Speech with long digital-silence gaps, as a breath script produces."""
    rng = np.random.default_rng(seed)
    audio = np.zeros(int(seconds * SR), dtype=np.float32)
    for start in (0, int(3 * SR)):
        n = int(1.0 * SR)
        audio[start : start + n] = (0.2 * rng.standard_normal(n)).astype(np.float32)
    return audio


def longest_silent_run(audio):
    """Length of the longest run of exactly-zero samples."""
    zero = np.concatenate(([False], audio == 0.0, [False]))
    edges = np.flatnonzero(zero[1:] != zero[:-1])
    return int(max((edges[1::2] - edges[::2]), default=0))


def test_room_tone_removes_digital_silence():
    from backend.utils.audio import add_room_tone

    audio = with_silence()
    assert float(np.mean(audio == 0.0)) > 0.5, "the fixture must have dead air to fill"
    # The fade ramps start and end on zero, so a lone sample at each edge is
    # expected; what must not survive is any audible stretch of dead air.
    assert longest_silent_run(add_room_tone(audio, SR)) <= 1


def test_room_tone_sits_at_the_requested_level():
    from backend.utils.audio import ROOM_TONE_LEVEL_DB, add_room_tone

    audio = with_silence()
    out = add_room_tone(audio, SR)
    pauses = out[np.abs(audio) < 1e-6]
    level = 20 * np.log10(float(np.sqrt(np.mean(pauses**2))))
    assert level == pytest.approx(ROOM_TONE_LEVEL_DB, abs=1.0)


def test_room_tone_does_not_change_perceived_loudness():
    audio = with_silence()
    from backend.utils.audio import add_room_tone

    assert measure_loudness(add_room_tone(audio, SR), SR) == pytest.approx(
        measure_loudness(audio, SR), abs=0.05
    )


def test_room_tone_is_continuous_so_word_gaps_are_covered_too():
    """A per-gap patch leaves the short gaps between words at zero."""
    from backend.utils.audio import add_room_tone

    rng = np.random.default_rng(2)
    audio = np.zeros(SR * 2, dtype=np.float32)
    # 50 ms of speech, 50 ms of gap — far shorter than any held pause.
    step = int(0.05 * SR)
    for start in range(0, len(audio) - step, 2 * step):
        audio[start : start + step] = (0.2 * rng.standard_normal(step)).astype(np.float32)

    assert longest_silent_run(add_room_tone(audio, SR)) <= 1


def test_room_tone_eases_in_at_the_edges():
    from backend.utils.audio import add_room_tone

    out = add_room_tone(np.zeros(SR, dtype=np.float32), SR)
    # The very first sample must not step straight to the floor level.
    assert abs(float(out[0])) < abs(float(out[SR // 2]))


def test_room_tone_handles_degenerate_input():
    from backend.utils.audio import add_room_tone

    assert add_room_tone(np.zeros(1, dtype=np.float32), SR).shape == (1,)
