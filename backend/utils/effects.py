"""
Audio post-processing effects engine.

Uses Spotify's pedalboard library to apply professional-grade DSP effects
to generated audio. Effects are described as a JSON-serializable chain
(list of effect dicts) so they can be stored in the database and sent
over the API.

Supported effect types:
  - chorus      (flanger-style with short delays)
  - reverb      (room reverb)
  - delay       (echo / delay line)
  - compressor  (dynamic range compression)
  - gain        (volume adjustment in dB)
  - highpass     (high-pass filter)
  - lowpass      (low-pass filter)
  - pitch_shift (semitone pitch shifting)
  - deesser     (tame sibilance without dulling the voice)
  - peak_eq     (bell EQ — presence, or notch a resonance)
  - high_shelf  (air above a corner frequency)
  - limiter     (ceiling before the file is written)

Most effects map straight onto a pedalboard plugin.  ``deesser`` has no
pedalboard equivalent, so it is implemented here and applied in chain
order alongside the plugins — see ``apply_effects``.
"""

from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from pedalboard import (
    Pedalboard,
    Chorus,
    Reverb,
    Compressor,
    Gain,
    HighShelfFilter,
    HighpassFilter,
    Limiter,
    LowpassFilter,
    Delay,
    NoiseGate,
    PeakFilter,
    PitchShift,
)


# Each param definition: (default, min, max, description)
EFFECT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "chorus": {
        "cls": Chorus,
        "label": "Chorus / Flanger",
        "description": "Modulated delay for flanging or chorus effects. Short centre_delay_ms (<10) gives flanger; longer gives chorus.",
        "params": {
            "rate_hz": {"default": 1.0, "min": 0.01, "max": 20.0, "step": 0.01, "description": "LFO speed (Hz)"},
            "depth": {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Modulation depth"},
            "feedback": {"default": 0.0, "min": 0.0, "max": 0.95, "step": 0.01, "description": "Feedback amount"},
            "centre_delay_ms": {
                "default": 7.0,
                "min": 0.5,
                "max": 50.0,
                "step": 0.1,
                "description": "Centre delay (ms)",
            },
            "mix": {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Wet/dry mix"},
        },
    },
    "reverb": {
        "cls": Reverb,
        "label": "Reverb",
        "description": "Room reverb effect.",
        "params": {
            "room_size": {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Room size"},
            "damping": {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "description": "High frequency damping"},
            "wet_level": {"default": 0.33, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Wet level"},
            "dry_level": {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Dry level"},
            "width": {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Stereo width"},
        },
    },
    "delay": {
        "cls": Delay,
        "label": "Delay",
        "description": "Echo / delay line.",
        "params": {
            "delay_seconds": {
                "default": 0.3,
                "min": 0.01,
                "max": 2.0,
                "step": 0.01,
                "description": "Delay time (seconds)",
            },
            "feedback": {"default": 0.3, "min": 0.0, "max": 0.95, "step": 0.01, "description": "Feedback amount"},
            "mix": {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01, "description": "Wet/dry mix"},
        },
    },
    "noise_gate": {
        "cls": NoiseGate,
        "label": "Noise Gate",
        "description": "Silences audio below a threshold — tames room-echo tails between phrases.",
        "params": {
            "threshold_db": {
                "default": -40.0,
                "min": -80.0,
                "max": 0.0,
                "step": 1.0,
                "description": "Level below which audio is gated (dB)",
            },
            "ratio": {"default": 4.0, "min": 1.0, "max": 20.0, "step": 0.5, "description": "Gate ratio"},
            "attack_ms": {"default": 1.0, "min": 0.1, "max": 100.0, "step": 0.1, "description": "Attack (ms)"},
            "release_ms": {"default": 120.0, "min": 10.0, "max": 1000.0, "step": 10.0, "description": "Release (ms)"},
        },
    },
    "compressor": {
        "cls": Compressor,
        "label": "Compressor",
        "description": "Dynamic range compression for consistent loudness.",
        "params": {
            "threshold_db": {"default": -20.0, "min": -60.0, "max": 0.0, "step": 0.5, "description": "Threshold (dB)"},
            "ratio": {"default": 4.0, "min": 1.0, "max": 20.0, "step": 0.1, "description": "Compression ratio"},
            "attack_ms": {"default": 10.0, "min": 0.1, "max": 100.0, "step": 0.1, "description": "Attack time (ms)"},
            "release_ms": {
                "default": 100.0,
                "min": 10.0,
                "max": 1000.0,
                "step": 1.0,
                "description": "Release time (ms)",
            },
        },
    },
    "gain": {
        "cls": Gain,
        "label": "Gain",
        "description": "Volume adjustment in decibels.",
        "params": {
            "gain_db": {"default": 0.0, "min": -40.0, "max": 40.0, "step": 0.5, "description": "Gain (dB)"},
        },
    },
    "highpass": {
        "cls": HighpassFilter,
        "label": "High-Pass Filter",
        "description": "Removes frequencies below the cutoff.",
        "params": {
            "cutoff_frequency_hz": {
                "default": 80.0,
                "min": 20.0,
                "max": 8000.0,
                "step": 1.0,
                "description": "Cutoff frequency (Hz)",
            },
        },
    },
    "lowpass": {
        "cls": LowpassFilter,
        "label": "Low-Pass Filter",
        "description": "Removes frequencies above the cutoff.",
        "params": {
            "cutoff_frequency_hz": {
                "default": 8000.0,
                "min": 200.0,
                "max": 20000.0,
                "step": 1.0,
                "description": "Cutoff frequency (Hz)",
            },
        },
    },
    "pitch_shift": {
        "cls": PitchShift,
        "label": "Pitch Shift",
        "description": "Shift pitch up or down by semitones.",
        "params": {
            "semitones": {"default": 0.0, "min": -12.0, "max": 12.0, "step": 0.5, "description": "Semitones to shift"},
        },
    },
    "deesser": {
        # No pedalboard equivalent — see _apply_deesser.
        "fn": "_apply_deesser",
        "label": "De-esser",
        "description": (
            "Compresses only the sibilance band, so harsh S sounds settle "
            "without dulling the voice. The threshold is an absolute level, "
            "calibrated for audio that has already been loudness-normalized "
            "— on a much quieter input it simply will not engage."
        ),
        "params": {
            "frequency_hz": {
                "default": 6000.0,
                "min": 2000.0,
                "max": 12000.0,
                "step": 100.0,
                "description": "Where sibilance starts (Hz)",
            },
            "threshold_db": {
                "default": -38.0,
                "min": -60.0,
                "max": 0.0,
                "step": 0.5,
                "description": "Threshold (dB)",
            },
            "ratio": {"default": 5.0, "min": 1.0, "max": 20.0, "step": 0.1, "description": "Compression ratio"},
        },
    },
    "peak_eq": {
        "cls": PeakFilter,
        "label": "Bell EQ",
        "description": "Boost or cut a band — presence around 3 kHz, or notch a resonance.",
        "params": {
            "cutoff_frequency_hz": {
                "default": 3000.0,
                "min": 40.0,
                "max": 16000.0,
                "step": 10.0,
                "description": "Centre frequency (Hz)",
            },
            "gain_db": {"default": 0.0, "min": -24.0, "max": 24.0, "step": 0.1, "description": "Gain (dB)"},
            "q": {"default": 0.8, "min": 0.1, "max": 10.0, "step": 0.1, "description": "Q (bandwidth)"},
        },
    },
    "high_shelf": {
        "cls": HighShelfFilter,
        "label": "High Shelf",
        "description": "Lifts or tames everything above the corner frequency — air, or the top off a bright clone.",
        "params": {
            "cutoff_frequency_hz": {
                "default": 8000.0,
                "min": 500.0,
                "max": 16000.0,
                "step": 10.0,
                "description": "Corner frequency (Hz)",
            },
            "gain_db": {"default": 0.0, "min": -24.0, "max": 24.0, "step": 0.1, "description": "Gain (dB)"},
            "q": {"default": 0.7, "min": 0.1, "max": 10.0, "step": 0.1, "description": "Q (slope)"},
        },
    },
    "limiter": {
        "cls": Limiter,
        "label": "Limiter",
        "description": (
            "Loudness maximizer: pushes the signal up against the ceiling. "
            "For a plain output ceiling you want the loudness normalization "
            "stage instead, which limits peaks without adding makeup gain."
        ),
        "params": {
            "threshold_db": {"default": -1.0, "min": -24.0, "max": 0.0, "step": 0.1, "description": "Ceiling (dB)"},
            "release_ms": {"default": 100.0, "min": 1.0, "max": 1000.0, "step": 1.0, "description": "Release (ms)"},
        },
    },
}


BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "robotic": {
        "name": "Robotic",
        "sort_order": 0,
        "description": "Metallic robotic voice (flanger with slow LFO and high feedback)",
        "effects_chain": [
            {
                "type": "chorus",
                "enabled": True,
                "params": {
                    "rate_hz": 0.2,
                    "depth": 1.0,
                    "feedback": 0.35,
                    "centre_delay_ms": 7.0,
                    "mix": 0.5,
                },
            },
        ],
    },
    "radio": {
        "name": "Radio",
        "sort_order": 1,
        "description": "Thin AM-radio voice with band-pass filtering and light compression",
        "effects_chain": [
            {
                "type": "highpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 300.0},
            },
            {
                "type": "lowpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 3500.0},
            },
            {
                "type": "compressor",
                "enabled": True,
                "params": {
                    "threshold_db": -15.0,
                    "ratio": 6.0,
                    "attack_ms": 5.0,
                    "release_ms": 50.0,
                },
            },
            {
                "type": "gain",
                "enabled": True,
                "params": {"gain_db": 6.0},
            },
        ],
    },
    "echo_chamber": {
        "name": "Echo Chamber",
        "sort_order": 2,
        "description": "Spacious reverb with trailing echo",
        "effects_chain": [
            {
                "type": "reverb",
                "enabled": True,
                "params": {
                    "room_size": 0.85,
                    "damping": 0.3,
                    "wet_level": 0.45,
                    "dry_level": 0.55,
                    "width": 1.0,
                },
            },
            {
                "type": "delay",
                "enabled": True,
                "params": {
                    "delay_seconds": 0.25,
                    "feedback": 0.3,
                    "mix": 0.2,
                },
            },
        ],
    },
    "voice_master": {
        "name": "Voice Master",
        "sort_order": 3,
        "description": "Broadcast finish for spoken word: rumble out, sibilance tamed, presence lifted. Expects loudness normalization on",
        "effects_chain": [
            # Rumble, HVAC and plosive thump live below the voice.
            {
                "type": "highpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 80.0},
            },
            # Before the compressor, so it never has an S to pump against.
            {
                "type": "deesser",
                "enabled": True,
                "params": {"frequency_hz": 6500.0, "threshold_db": -38.0, "ratio": 5.0},
            },
            # Gentle: 2:1 evens out the delivery without flattening a breath.
            {
                "type": "compressor",
                "enabled": True,
                "params": {
                    "threshold_db": -18.0,
                    "ratio": 2.0,
                    "attack_ms": 12.0,
                    "release_ms": 180.0,
                },
            },
            # A small presence lift is what reads as "close to the mic".
            {
                "type": "peak_eq",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 3000.0, "gain_db": 1.5, "q": 0.8},
            },
        ],
    },
    "meditation_voice": {
        "name": "Meditation Voice",
        "sort_order": 4,
        "description": "Warm and uncompressed — the opposite of a broadcast finish. For guided practice, where a presence lift reads as advertising",
        "effects_chain": [
            {
                "type": "highpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 70.0},
            },
            {
                "type": "deesser",
                "enabled": True,
                "params": {"frequency_hz": 6500.0, "threshold_db": -40.0, "ratio": 6.0},
            },
            # 1.6:1 with a slow attack: catches the odd loud word and leaves
            # the breath, the decay and the quiet endings where they are.
            {
                "type": "compressor",
                "enabled": True,
                "params": {
                    "threshold_db": -24.0,
                    "ratio": 1.6,
                    "attack_ms": 25.0,
                    "release_ms": 400.0,
                },
            },
            # No presence bell here. Lifting 3 kHz is exactly what makes a
            # voice sound like it is selling something; this takes the edge
            # off the top instead.
            {
                "type": "high_shelf",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 7000.0, "gain_db": -2.0, "q": 0.7},
            },
        ],
    },
    "meditation_room": {
        "name": "Meditation Room",
        "sort_order": 5,
        "description": "Voice Master plus a small controlled room — a space, not a bathroom. Expects loudness normalization on",
        "effects_chain": [
            {
                "type": "highpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 80.0},
            },
            {
                "type": "deesser",
                "enabled": True,
                "params": {"frequency_hz": 6500.0, "threshold_db": -40.0, "ratio": 6.0},
            },
            {
                "type": "compressor",
                "enabled": True,
                "params": {
                    "threshold_db": -20.0,
                    "ratio": 2.0,
                    "attack_ms": 15.0,
                    "release_ms": 250.0,
                },
            },
            # Small and mostly dry: enough to place the voice in a space,
            # not enough to smear the held silences.
            {
                "type": "reverb",
                "enabled": True,
                "params": {
                    "room_size": 0.32,
                    "damping": 0.6,
                    "wet_level": 0.14,
                    "dry_level": 0.9,
                    "width": 0.8,
                },
            },
        ],
    },
    "deep_voice": {
        "name": "Deep Voice",
        "sort_order": 99,
        "description": "Lower pitch with added warmth",
        "effects_chain": [
            {
                "type": "pitch_shift",
                "enabled": True,
                "params": {"semitones": -3.0},
            },
            {
                "type": "lowpass",
                "enabled": True,
                "params": {"cutoff_frequency_hz": 6000.0},
            },
            {
                "type": "compressor",
                "enabled": True,
                "params": {
                    "threshold_db": -18.0,
                    "ratio": 3.0,
                    "attack_ms": 10.0,
                    "release_ms": 150.0,
                },
            },
        ],
    },
}


def get_available_effects() -> List[Dict[str, Any]]:
    """Return the list of available effect types with their parameter definitions.

    Used by the frontend to build the effects chain editor UI.
    """
    result = []
    for effect_type, info in EFFECT_REGISTRY.items():
        result.append(
            {
                "type": effect_type,
                "label": info["label"],
                "description": info["description"],
                "params": {name: {k: v for k, v in pdef.items()} for name, pdef in info["params"].items()},
            }
        )
    return result


def get_builtin_presets() -> Dict[str, Dict[str, Any]]:
    """Return all built-in effect presets."""
    return BUILTIN_PRESETS


def validate_effects_chain(effects_chain: List[Dict[str, Any]]) -> Optional[str]:
    """Validate an effects chain configuration.

    Returns None if valid, or an error message string.
    """
    if not isinstance(effects_chain, list):
        return "effects_chain must be a list"

    for i, effect in enumerate(effects_chain):
        if not isinstance(effect, dict):
            return f"Effect at index {i} must be a dict"

        effect_type = effect.get("type")
        if effect_type not in EFFECT_REGISTRY:
            return f"Unknown effect type '{effect_type}' at index {i}. Available: {list(EFFECT_REGISTRY.keys())}"

        params = effect.get("params", {})
        if not isinstance(params, dict):
            return f"Effect '{effect_type}' at index {i}: params must be a dict"

        registry = EFFECT_REGISTRY[effect_type]
        for param_name, value in params.items():
            if param_name not in registry["params"]:
                return f"Effect '{effect_type}' at index {i}: unknown param '{param_name}'"

            pdef = registry["params"][param_name]
            if not isinstance(value, (int, float)):
                return f"Effect '{effect_type}' at index {i}: param '{param_name}' must be a number"
            if value < pdef["min"] or value > pdef["max"]:
                return (
                    f"Effect '{effect_type}' at index {i}: param '{param_name}' "
                    f"must be between {pdef['min']} and {pdef['max']} (got {value})"
                )

    return None


def _resolved_params(effect: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an effect's configured params over the registry defaults."""
    registry = EFFECT_REGISTRY[effect["type"]]
    provided = effect.get("params", {})
    return {
        name: provided.get(name, pdef["default"])
        for name, pdef in registry["params"].items()
    }


def _apply_deesser(
    audio: np.ndarray,
    sample_rate: int,
    frequency_hz: float,
    threshold_db: float,
    ratio: float,
) -> np.ndarray:
    """Compress only the sibilance band and put the voice back together.

    The band split is complementary rather than a filter pair: the low band
    is what is *left over* after the high-pass, so low + high reconstructs
    the input exactly and no phase notch appears at the crossover. Only the
    high band meets the compressor, which is what separates a de-esser from
    simply rolling off the top of a voice.
    """
    high = Pedalboard([HighpassFilter(cutoff_frequency_hz=frequency_hz)])(audio, sample_rate)
    low = audio - high
    tamed = Pedalboard(
        [
            Compressor(
                threshold_db=threshold_db,
                ratio=ratio,
                # Fast enough to catch an S, slow enough to let it decay.
                attack_ms=1.0,
                release_ms=40.0,
            )
        ]
    )(high, sample_rate)
    return low + tamed


# Effects implemented here rather than by a pedalboard plugin.
CUSTOM_EFFECTS = {"deesser": _apply_deesser}


def build_pedalboard(effects_chain: List[Dict[str, Any]]) -> Pedalboard:
    """Build a Pedalboard instance from an effects chain config.

    Skips effects where ``enabled`` is ``False``, and effects in
    :data:`CUSTOM_EFFECTS`, which have no plugin to build. Use
    :func:`apply_effects` to run a chain that may contain either kind.
    """
    plugins = []
    for effect in effects_chain:
        if not effect.get("enabled", True):
            continue
        if effect["type"] in CUSTOM_EFFECTS:
            continue

        plugins.append(EFFECT_REGISTRY[effect["type"]]["cls"](**_resolved_params(effect)))

    return Pedalboard(plugins)


def apply_effects(
    audio: np.ndarray,
    sample_rate: int,
    effects_chain: List[Dict[str, Any]],
) -> np.ndarray:
    """Apply an effects chain to audio data.

    Args:
        audio: Input audio array (1-D mono float32).
        sample_rate: Sample rate in Hz.
        effects_chain: List of effect configuration dicts.

    Returns:
        Processed audio array.
    """
    if not effects_chain:
        return audio

    # pedalboard expects shape (channels, samples)
    if audio.ndim == 1:
        audio_2d = audio[np.newaxis, :]
    else:
        audio_2d = audio

    processed = audio_2d.astype(np.float32)

    # Chain order matters — a de-esser before the compressor is not the same
    # chain as one after it — so consecutive plugins are batched into a board
    # and the custom effects run between the batches, in the order given.
    pending: List[Dict[str, Any]] = []

    def _flush(signal: np.ndarray) -> np.ndarray:
        if not pending:
            return signal
        board = build_pedalboard(pending)
        pending.clear()
        return board(signal, sample_rate)

    for effect in effects_chain:
        if not effect.get("enabled", True):
            continue
        custom = CUSTOM_EFFECTS.get(effect["type"])
        if custom is None:
            pending.append(effect)
            continue
        processed = _flush(processed)
        processed = custom(processed, sample_rate, **_resolved_params(effect))

    processed = _flush(processed)

    # Return same dimensionality as input
    if audio.ndim == 1:
        return processed[0]
    return processed
