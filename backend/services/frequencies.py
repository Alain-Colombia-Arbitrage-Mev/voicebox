"""
Healing-frequency and brainwave-entrainment audio synthesis.

Generates pure tones (solfeggio/abundance frequencies like 396/432/528/
777/888 Hz), Schumann-resonance entrainment, and brainwave-band programs
(delta/theta/alpha/beta/gamma) as either:

- binaural beats — stereo, left/right carriers offset by the beat
  frequency; requires headphones,
- isochronic pulses — amplitude-gated carrier; works on speakers and
  survives the mono story-export mixdown,
- pure tones — plain carrier, no modulation.

Everything is synthesized locally with numpy (instant, offline, free)
and registered as a Generation row under a singleton "Frequencies"
profile so tones drop straight onto the story timeline next to voices
and music.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FREQUENCY_SAMPLE_RATE = 44100
MAX_DURATION_SEC = 1800  # 30 min cap keeps files manageable (~150-300 MB)
FADE_SEC = 3.0


@dataclass
class FrequencyPreset:
    """A named tone/entrainment program."""

    key: str
    name: str
    description: str
    carrier_hz: float
    beat_hz: float = 0.0  # 0 = pure tone
    mode: str = "pure"  # pure | binaural | isochronic
    tags: list[str] = field(default_factory=list)


# Solfeggio / abundance carriers + Schumann + brainwave bands.
# Brainwave beats ride on a 432 Hz carrier by default — the band frequency
# itself is below hearing range and must be delivered as a beat.
FREQUENCY_PRESETS: list[FrequencyPreset] = [
    FrequencyPreset(
        key="888hz-prosperidad",
        name="888 Hz — Prosperidad",
        description="Activa la prosperidad financiera y la conexión con la riqueza ilimitada del universo.",
        carrier_hz=888.0,
        tags=["solfeggio", "abundancia"],
    ),
    FrequencyPreset(
        key="777hz-suerte",
        name="777 Hz — Buena suerte",
        description="Atrae la buena suerte, abre caminos y fomenta la fe en el éxito económico.",
        carrier_hz=777.0,
        tags=["solfeggio", "abundancia"],
    ),
    FrequencyPreset(
        key="528hz-amor",
        name="528 Hz — Amor y transformación",
        description="La frecuencia del amor y la transformación: repara y limpia bloqueos mentales.",
        carrier_hz=528.0,
        tags=["solfeggio"],
    ),
    FrequencyPreset(
        key="432hz-armonia",
        name="432 Hz — Armonía natural",
        description="Alinea mente y cuerpo con el entorno natural para reducir el estrés y la escasez mental.",
        carrier_hz=432.0,
        tags=["solfeggio"],
    ),
    FrequencyPreset(
        key="396hz-liberacion",
        name="396 Hz — Liberación",
        description="Ayuda a liberar el miedo inconsciente, la culpa y la resistencia al éxito.",
        carrier_hz=396.0,
        tags=["solfeggio"],
    ),
    FrequencyPreset(
        key="schumann",
        name="Resonancia Schumann — 7.83 Hz",
        description="El pulso natural de la Tierra como batido binaural sobre 432 Hz. Conexión y enraizamiento.",
        carrier_hz=432.0,
        beat_hz=7.83,
        mode="binaural",
        tags=["schumann", "tierra"],
    ),
    FrequencyPreset(
        key="delta-sueno",
        name="Delta 2 Hz — Sueño profundo",
        description="Mantras de sueño y descanso; acompaña voz muy lenta y grave.",
        carrier_hz=432.0,
        beat_hz=2.0,
        mode="binaural",
        tags=["banda", "delta"],
    ),
    FrequencyPreset(
        key="theta-meditacion",
        name="Theta 6 Hz — Meditación profunda",
        description="Calma, liberación y meditación profunda.",
        carrier_hz=432.0,
        beat_hz=6.0,
        mode="binaural",
        tags=["banda", "theta"],
    ),
    FrequencyPreset(
        key="alpha-gratitud",
        name="Alpha 10 Hz — Relajación y gratitud",
        description="Relajación consciente, gratitud y amor.",
        carrier_hz=432.0,
        beat_hz=10.0,
        mode="binaural",
        tags=["banda", "alpha"],
    ),
    FrequencyPreset(
        key="beta-abundancia",
        name="Beta 15 Hz — Abundancia y foco",
        description="Abundancia, trabajo y foco; acompaña una voz más presente.",
        carrier_hz=528.0,
        beat_hz=15.0,
        mode="binaural",
        tags=["banda", "beta"],
    ),
    FrequencyPreset(
        key="gamma-poder",
        name="Gamma 40 Hz — Poder personal",
        description="Poder personal y creatividad.",
        carrier_hz=528.0,
        beat_hz=40.0,
        mode="binaural",
        tags=["banda", "gamma"],
    ),
]

_PRESETS_BY_KEY = {p.key: p for p in FREQUENCY_PRESETS}


def get_preset(key: str) -> FrequencyPreset | None:
    return _PRESETS_BY_KEY.get(key)


def synthesize(
    *,
    carrier_hz: float,
    beat_hz: float = 0.0,
    mode: str = "pure",
    duration_sec: float = 300.0,
    volume: float = 0.5,
    sample_rate: int = FREQUENCY_SAMPLE_RATE,
) -> np.ndarray:
    """Render the tone program. Returns float32 mono (n,) or stereo (n, 2).

    Binaural mode returns stereo (left carrier, right carrier+beat).
    Isochronic mode gates the carrier amplitude at the beat rate with a
    smoothed square wave. A gentle breathing LFO keeps long pure tones
    from feeling static, and edges get a fade in/out.
    """
    duration_sec = float(np.clip(duration_sec, 10.0, MAX_DURATION_SEC))
    volume = float(np.clip(volume, 0.05, 1.0))
    n = int(duration_sec * sample_rate)
    t = np.arange(n, dtype=np.float64) / sample_rate

    def tone(freq_hz: float) -> np.ndarray:
        return np.sin(2 * np.pi * freq_hz * t)

    if mode == "binaural" and beat_hz > 0:
        left = tone(carrier_hz)
        right = tone(carrier_hz + beat_hz)
        audio = np.stack([left, right], axis=1)
    elif mode == "isochronic" and beat_hz > 0:
        # Smoothed on/off gate at the beat rate (raised-cosine edges)
        gate = 0.5 * (1.0 + np.sin(2 * np.pi * beat_hz * t - np.pi / 2))
        gate = gate**1.5  # deepen the troughs so pulses read clearly
        audio = tone(carrier_hz) * gate
    else:
        audio = tone(carrier_hz)

    # Slow breathing LFO (12s period, ±10%) so long tones stay organic
    lfo = 1.0 - 0.1 * (0.5 * (1.0 + np.sin(2 * np.pi * t / 12.0)))
    audio = audio * (lfo if audio.ndim == 1 else lfo[:, None])

    # Fade edges to avoid clicks
    fade_n = min(int(FADE_SEC * sample_rate), n // 4)
    if fade_n > 0:
        ramp = np.linspace(0.0, 1.0, fade_n)
        if audio.ndim == 1:
            audio[:fade_n] *= ramp
            audio[-fade_n:] *= ramp[::-1]
        else:
            audio[:fade_n] *= ramp[:, None]
            audio[-fade_n:] *= ramp[::-1][:, None]

    return (audio * volume).astype(np.float32)
