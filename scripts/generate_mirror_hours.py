#!/usr/bin/env python3
"""Render the 720 mirror-hours library to audio, one file per hour.

Each row of the library carries three texts that want three different
deliveries: the message is narrated, the somatic micro-gesture is a guided
practice that breathes, and the "YO SOY" affirmation lands one statement at
a time. They are generated separately so each gets its own breath script,
then joined with silence — a single request could not change register
halfway through.

The backend must be running with the repo's code (not the installed build)
and pointed at a data dir holding a MiniMax key:

    python -m backend.main --port 17494 --data-dir "<app support dir>"

Usage:
    scripts/generate_mirror_hours.py --profile <id> --out <dir>
    scripts/generate_mirror_hours.py --profile <id> --out <dir> --limit 3
    scripts/generate_mirror_hours.py --list-rows
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import wave
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import urllib.error
import urllib.request

LIBRARY_XLSX = (
    "/Volumes/KINGSTON/Mandalaapp/mandala_app/docs/Biblioteca_720_Horas_Espejo_Mes.xlsx"
)
DEFAULT_SERVER = "http://127.0.0.1:17494"

# Column indexes in the library sheet.
COL_ID, COL_DAY, COL_THEME, COL_HOUR = 0, 1, 2, 3
COL_CATEGORY, COL_MESSAGE, COL_GESTURE, COL_AFFIRMATION = 5, 8, 9, 10

# Each section: (column, breath style, silence after it in seconds).
SECTIONS = (
    (COL_MESSAGE, "narration", 1.2),
    (COL_GESTURE, "meditation", 1.8),
    (COL_AFFIRMATION, "affirmation", 0.0),
)

MASTERING_PRESET = "Meditation Voice"

# The library names a frequency per row. A tone bed is available, but it is
# off by default: the pieces are wanted as voice only. The synthetic-silence
# problem it used to solve is handled by room tone instead.
COL_FREQUENCY = 12
BED_GAIN_DB = -26.0


@dataclass
class Row:
    piece_id: str
    day: str
    hour: str
    category: str
    texts: dict[int, str]
    frequency_hz: float | None

    @property
    def filename(self) -> str:
        return f"{self.piece_id}_{self.hour.replace(':', '')}.wav"


# ── library ───────────────────────────────────────────────────────────


def read_library(path: str) -> list[Row]:
    """Parse the sheet directly: openpyxl is not a backend dependency."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    tag_t = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"

    with zipfile.ZipFile(path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")

    rows: list[Row] = []
    for record in ET.fromstring(sheet).find("m:sheetData", ns):
        cells: list[str] = []
        for cell in record.findall("m:c", ns):
            inline = cell.find("m:is", ns)
            if inline is not None:
                cells.append("".join(node.text or "" for node in inline.iter(tag_t)))
            else:
                value = cell.find("m:v", ns)
                cells.append(value.text if value is not None else "")
        if len(cells) < 14 or cells[COL_ID] == "ID":
            continue
        rows.append(
            Row(
                piece_id=cells[COL_ID],
                day=cells[COL_DAY],
                hour=cells[COL_HOUR],
                category=cells[COL_CATEGORY],
                texts={col: cells[col] for col, _, _ in SECTIONS},
                frequency_hz=_as_float(cells[COL_FREQUENCY]),
            )
        )
    return rows


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── frequency bed ─────────────────────────────────────────────────────


def mix_frequency_bed(wav_bytes: bytes, carrier_hz: float, gain_db: float = BED_GAIN_DB) -> bytes:
    """Lay a continuous tone under the piece at the given level."""
    import numpy as np
    import soundfile as sf

    from backend.services.frequencies import synthesize

    voice, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    if voice.ndim > 1:
        voice = voice.mean(axis=1)

    seconds = len(voice) / sample_rate
    bed = synthesize(
        carrier_hz=carrier_hz,
        duration_sec=max(seconds, 10.0),
        volume=1.0,
        sample_rate=sample_rate,
    )
    if bed.ndim > 1:
        bed = bed.mean(axis=1)
    bed = bed[: len(voice)]
    if len(bed) < len(voice):
        bed = np.pad(bed, (0, len(voice) - len(bed)), mode="edge")

    mixed = voice + bed * (10 ** (gain_db / 20))

    # The voice was already limited to its ceiling; the bed adds on top.
    from backend.utils.audio import DEFAULT_CEILING_DB, limit_peaks

    ceiling = 10 ** (DEFAULT_CEILING_DB / 20)
    if float(np.abs(mixed).max()) > ceiling:
        mixed = limit_peaks(mixed, sample_rate, ceiling)

    buffer = io.BytesIO()
    sf.write(buffer, mixed, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


# ── synthesis ─────────────────────────────────────────────────────────


def synthesize(server: str, profile_id: str, text: str, breath_style: str,
               preset_chain: list | None, speed: float | None = None,
               intensity: int | None = None, timeout: float = 180.0) -> bytes:
    """One section of one piece, mastered, as wav bytes."""
    payload = {
        "profile_id": profile_id,
        "text": text,
        "language": "es",
        "engine": "minimax",
        "emotion": "calm",
        "breath_style": breath_style,
        "normalize": True,
    }
    if speed is not None:
        payload["speed"] = speed
    if intensity is not None:
        payload["intensity"] = intensity
    if preset_chain is not None:
        payload["effects_chain"] = preset_chain

    request = urllib.request.Request(
        f"{server}/generate/stream",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def join_sections(sections: list[tuple[bytes, float]]) -> bytes:
    """Concatenate wav sections, inserting exact silence between them."""
    frames: list[bytes] = []
    params = None

    for index, (wav_bytes, gap_seconds) in enumerate(sections):
        with wave.open(io.BytesIO(wav_bytes)) as source:
            if params is None:
                params = source.getparams()
            elif (source.getframerate(), source.getsampwidth(), source.getnchannels()) != (
                params.framerate, params.sampwidth, params.nchannels
            ):
                raise RuntimeError("sections came back in different audio formats")
            frames.append(source.readframes(source.getnframes()))

        is_last = index == len(sections) - 1
        if gap_seconds > 0 and not is_last:
            silence = int(gap_seconds * params.framerate) * params.sampwidth * params.nchannels
            frames.append(b"\x00" * silence)

    if params is None:
        raise RuntimeError("nothing to join")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(b"".join(frames))
    return buffer.getvalue()


def render_piece(server: str, profile_id: str, row: Row, preset_chain: list | None,
                 speed: float | None = None, intensity: int | None = None,
                 bed: bool = False) -> bytes:
    sections = []
    for column, style, gap in SECTIONS:
        text = row.texts[column].strip()
        if not text:
            continue
        sections.append(
            (synthesize(server, profile_id, text, style, preset_chain, speed, intensity), gap)
        )
    audio = join_sections(sections)
    if bed and row.frequency_hz:
        audio = mix_frequency_bed(audio, row.frequency_hz)
    else:
        audio = apply_room_tone(audio)
    return audio


def apply_room_tone(wav_bytes: bytes) -> bytes:
    """Give the held pauses a noise floor so they stop sounding synthetic."""
    import soundfile as sf

    from backend.utils.audio import add_room_tone

    audio, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    filled = add_room_tone(audio, sample_rate)

    buffer = io.BytesIO()
    sf.write(buffer, filled, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


# ── mastering preset ──────────────────────────────────────────────────


def fetch_preset_chain(server: str, name: str) -> list | None:
    with urllib.request.urlopen(f"{server}/effects/presets", timeout=30) as response:
        payload = json.load(response)
    presets = payload if isinstance(payload, list) else payload.get("presets", [])
    for preset in presets:
        if preset.get("name") == name:
            chain = preset.get("effects_chain")
            return json.loads(chain) if isinstance(chain, str) else chain
    return None


# ── cli ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", help="Voice profile id to render with")
    parser.add_argument("--out", help="Directory to write the wav files into")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--library", default=LIBRARY_XLSX)
    parser.add_argument("--limit", type=int, help="Render only the first N rows")
    parser.add_argument("--only", nargs="*", help="Render only these piece ids")
    parser.add_argument("--no-mastering", action="store_true", help="Skip the effects chain")
    parser.add_argument("--bed", action="store_true",
                        help="Mix the row's frequency under the voice (off by default)")
    parser.add_argument("--speed", type=float, help="Speech rate override")
    parser.add_argument("--intensity", type=int, help="Delivery intensity [-100, 100]; negative is softer")
    parser.add_argument("--list-rows", action="store_true", help="Print the library and exit")
    args = parser.parse_args()

    rows = read_library(args.library)

    if args.list_rows:
        for row in rows[:40]:
            print(f"{row.piece_id}  {row.hour}  {row.category}")
        print(f"... {len(rows)} rows total")
        return 0

    if not args.profile or not args.out:
        parser.error("--profile and --out are required unless --list-rows is given")

    if args.only:
        wanted = set(args.only)
        rows = [row for row in rows if row.piece_id in wanted]
    if args.limit:
        rows = rows[: args.limit]

    preset_chain = None if args.no_mastering else fetch_preset_chain(args.server, MASTERING_PRESET)
    if preset_chain is None and not args.no_mastering:
        print(f"! mastering preset {MASTERING_PRESET!r} not found — rendering dry", file=sys.stderr)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    started = time.time()

    for index, row in enumerate(rows, start=1):
        target = out_dir / row.filename
        if target.exists():
            print(f"[{index}/{len(rows)}] {row.piece_id} — ya existe, se omite")
            continue
        try:
            audio = render_piece(args.server, args.profile, row, preset_chain,
                                 args.speed, args.intensity, bed=args.bed)
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as error:
            detail = error.read().decode()[:200] if hasattr(error, "read") else str(error)
            print(f"[{index}/{len(rows)}] {row.piece_id} — FALLO: {detail}", file=sys.stderr)
            failures.append((row.piece_id, detail))
            continue

        target.write_bytes(audio)
        with wave.open(io.BytesIO(audio)) as probe:
            seconds = probe.getnframes() / probe.getframerate()
        elapsed = time.time() - started
        print(f"[{index}/{len(rows)}] {row.piece_id} {row.hour} — {seconds:5.1f}s "
              f"({target.stat().st_size // 1024} KB) · {elapsed / index:.1f}s/pieza")

    print(f"\nListo: {len(rows) - len(failures)}/{len(rows)} piezas en {out_dir}")
    if failures:
        print(f"Fallos: {len(failures)}", file=sys.stderr)
        for piece_id, detail in failures[:10]:
            print(f"  {piece_id}: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
