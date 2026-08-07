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
        key="1111hz-portal",
        name="1111 Hz — Portal de manifestación",
        description="La frecuencia angelical 11:11: alineación espiritual, sincronicidad y manifestación de deseos.",
        carrier_hz=1111.0,
        tags=["angelical", "manifestacion"],
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
    # Bells and gongs tuned to exact frequencies — inharmonic partial
    # synthesis (real bell physics). beat_hz carries the strike rate.
    FrequencyPreset(
        key="campana-432",
        name="Campanas 432 Hz — Armonía",
        description="Campanas de bronce afinadas a 432 Hz exactos, un tañido sereno cada 12 segundos.",
        carrier_hz=432.0,
        beat_hz=1.0 / 12.0,
        mode="bell",
        tags=["campanas", "manifestacion"],
    ),
    FrequencyPreset(
        key="campana-888",
        name="Campanas 888 Hz — Prosperidad",
        description="Campanas afinadas a 888 Hz, llamando a la abundancia cada 12 segundos.",
        carrier_hz=888.0,
        beat_hz=1.0 / 12.0,
        mode="bell",
        tags=["campanas", "abundancia"],
    ),
    FrequencyPreset(
        key="campana-1111",
        name="Campanas 1111 Hz — Manifestación",
        description="Campanas del portal 11:11, un tañido cristalino cada 10 segundos.",
        carrier_hz=1111.0,
        beat_hz=0.1,
        mode="bell",
        tags=["campanas", "manifestacion"],
    ),
    FrequencyPreset(
        key="gong-om",
        name="Gong Om — 136.1 Hz",
        description="Gong profundo en la frecuencia del Om (136.1 Hz), resonancia larga cada 25 segundos.",
        carrier_hz=136.1,
        beat_hz=0.04,
        mode="gong",
        tags=["gong", "om"],
    ),
    # Breathing therapy: the isochronic gate at breathing rate turns the
    # carrier into soft swells that pace inhale/exhale — a guide sound,
    # not music. 0.1 Hz = 10 s cycle = 6 breaths/min (coherent breathing).
    FrequencyPreset(
        key="respiracion-coherente",
        name="Respiración coherente — 6/min",
        description="Oleadas suaves de 10 segundos que guían la inhalación y exhalación (respiración coherente).",
        carrier_hz=432.0,
        beat_hz=0.1,
        mode="isochronic",
        tags=["respiracion", "terapia"],
    ),
    FrequencyPreset(
        key="respiracion-profunda",
        name="Respiración profunda — 4/min",
        description="Ciclos de 15 segundos para respiración muy lenta y meditación profunda.",
        carrier_hz=396.0,
        beat_hz=1.0 / 15.0,
        mode="isochronic",
        tags=["respiracion", "terapia"],
    ),
]

_PRESETS_BY_KEY = {p.key: p for p in FREQUENCY_PRESETS}


def get_preset(key: str) -> FrequencyPreset | None:
    return _PRESETS_BY_KEY.get(key)


# Inharmonic partial sets — (ratio to fundamental, amplitude, decay seconds).
# Bell ratios follow the classic minor-third church bell profile (hum,
# prime, tierce, quint, nominal…); gong partials are denser and lower.
_BELL_PARTIALS = [
    (0.56, 0.5, 8.0),
    (0.92, 0.7, 7.0),
    (1.0, 1.0, 6.0),
    (1.19, 0.6, 5.0),
    (1.71, 0.4, 4.0),
    (2.0, 0.5, 3.5),
    (2.74, 0.3, 2.5),
    (3.0, 0.25, 2.0),
    (3.76, 0.15, 1.5),
    (4.07, 0.1, 1.2),
]
_GONG_PARTIALS = [
    (0.41, 1.0, 14.0),
    (0.56, 0.7, 12.0),
    (0.83, 0.8, 12.0),
    (1.0, 1.0, 10.0),
    (1.23, 0.6, 9.0),
    (1.53, 0.5, 8.0),
    (1.94, 0.4, 6.0),
    (2.51, 0.35, 5.0),
    (3.01, 0.3, 4.0),
    (3.8, 0.2, 3.0),
]


def _render_strike(f0: float, sr: int, length_sec: float, gong: bool) -> np.ndarray:
    """One bell/gong strike: sum of exponentially decaying inharmonic partials."""
    n = int(length_sec * sr)
    t = np.arange(n, dtype=np.float64) / sr
    partials = _GONG_PARTIALS if gong else _BELL_PARTIALS
    out = np.zeros(n, dtype=np.float64)
    for ratio, amp, decay in partials:
        f = f0 * ratio
        if f >= sr * 0.45:
            continue
        # Slight detune per partial adds natural beating/shimmer
        detune = 1.0 + 0.0015 * np.sin(ratio * 12.9898)
        out += amp * np.sin(2 * np.pi * f * detune * t) * np.exp(-t / decay)
    # Attack: bells ring instantly, gongs swell in
    attack = int((0.25 if gong else 0.008) * sr)
    if attack > 0:
        out[:attack] *= np.linspace(0.0, 1.0, attack) ** (0.5 if gong else 1.0)
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak).astype(np.float64)


def _synthesize_strikes(
    carrier_hz: float,
    strike_interval_sec: float,
    duration_sec: float,
    sample_rate: int,
    gong: bool,
) -> np.ndarray:
    """A meditative strike train with humanized timing and level."""
    n = int(duration_sec * sample_rate)
    out = np.zeros(n, dtype=np.float64)
    ring = min(strike_interval_sec * 2.5, 30.0)
    strike = _render_strike(carrier_hz, sample_rate, ring, gong)

    rng = np.random.default_rng(int(carrier_hz * 10))  # deterministic per pitch
    t = 0.5  # first strike shortly after the start
    while t < duration_sec:
        start = int(t * sample_rate)
        end = min(n, start + len(strike))
        level = 0.85 + 0.15 * rng.random()
        out[start:end] += strike[: end - start] * level
        t += strike_interval_sec * (0.92 + 0.16 * rng.random())

    peak = np.max(np.abs(out)) or 1.0
    if peak > 1.0:
        out /= peak
    return out


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

    # Bell/gong strike trains skip the breathing LFO — their own decay
    # envelope IS the movement. Edge fades still apply.
    if mode in ("bell", "gong"):
        interval = (1.0 / beat_hz) if beat_hz > 0 else 12.0
        audio = _synthesize_strikes(
            carrier_hz, interval, duration_sec, sample_rate, gong=(mode == "gong")
        )
        fade_n = min(int(FADE_SEC * sample_rate), n // 4)
        if fade_n > 0:
            ramp = np.linspace(0.0, 1.0, fade_n)
            audio[:fade_n] *= ramp
            audio[-fade_n:] *= ramp[::-1]
        return (audio * volume).astype(np.float32)

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


def _loop_to_length(audio: np.ndarray, target_n: int, sample_rate: int) -> np.ndarray:
    """Extend audio to target_n samples by crossfade-looping (2s overlap)."""
    if audio.shape[0] >= target_n:
        return audio[:target_n]
    xfade = min(int(2.0 * sample_rate), audio.shape[0] // 4)
    out = audio
    while out.shape[0] < target_n:
        ramp = np.linspace(0.0, 1.0, xfade, dtype=np.float32)
        ramp = ramp if out.ndim == 1 else ramp[:, None]
        head = audio[:xfade] * ramp
        tail = out[-xfade:] * (1.0 - ramp)
        out = np.concatenate([out[:-xfade], tail + head, audio[xfade:]])
    return out[:target_n]


def infuse_tone_into_music(
    music: np.ndarray,
    music_sr: int,
    *,
    carrier_hz: float,
    beat_hz: float = 0.0,
    mode: str = "pure",
    duration_sec: float = 300.0,
    tone_volume: float = 0.3,
) -> np.ndarray:
    """Blend an exact synthesized frequency under AI-generated music.

    The music provides the texture; the embedded tone carries the true
    frequency content (an AI music model cannot guarantee exact Hz).
    Music shorter than the requested duration is crossfade-looped. Output
    is stereo when either source is stereo (binaural tones force stereo).
    """
    duration_sec = float(np.clip(duration_sec, 10.0, MAX_DURATION_SEC))
    target_n = int(duration_sec * music_sr)

    music = _loop_to_length(music.astype(np.float32), target_n, music_sr)
    tone = synthesize(
        carrier_hz=carrier_hz,
        beat_hz=beat_hz,
        mode=mode,
        duration_sec=duration_sec,
        volume=tone_volume,
        sample_rate=music_sr,
    )
    tone = tone[:target_n]

    # Promote both to stereo if either is stereo
    if music.ndim == 1 and tone.ndim == 2:
        music = np.stack([music, music], axis=1)
    elif tone.ndim == 1 and music.ndim == 2:
        tone = np.stack([tone, tone], axis=1)

    n = min(music.shape[0], tone.shape[0])
    mixed = music[:n] * 0.9 + tone[:n]

    peak = float(np.max(np.abs(mixed))) or 1.0
    if peak > 0.95:
        mixed = mixed * (0.95 / peak)
    return mixed.astype(np.float32)
