"""Render the Mantralia professional podcast voiceover through Voicebox's persisted generation pipeline.

Example: python scripts/render_mantralia.py --engine qwen --preview
The running server owns credentials; this client never needs API keys.
"""

import argparse
import io
import json
import time
from pathlib import Path

import httpx
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app/src/lib/constants/mantralia-claridad.json"


def compile_script(engine, preview=False):
    script = json.loads(SCRIPT.read_text())
    segments = script["segments"][:5] if preview else script["segments"]
    lines = []
    for segment in segments:
        cue = f"[{segment['emotion']}] " if engine == "fish" else ""
        breath = segment.get("breath")
        if breath:
            tag = f" [{('exhale' if breath == 'breath' else breath)}]" if engine == "fish" else f" ({breath})"
        else:
            tag = ""
        pause = f" <#{segment['pause_after']}#>" if engine != 'qwen' else ''
        lines.append(f"{cue}{segment['text']}{tag}{pause}")
    return script, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["fish", "minimax", "qwen"], default="qwen")
    parser.add_argument("--profile", default="Mantralia · Referencia Argentina · Narración", help="Voicebox profile name or ID")
    parser.add_argument("--server", default="http://127.0.0.1:17493")
    parser.add_argument("--preview", action="store_true", help="Generate only the opening and editorial question")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-scripts", action="store_true", help="Write both provider scripts without generation")
    args = parser.parse_args()
    if args.export_scripts:
        for engine in ("fish", "minimax"):
            _, text = compile_script(engine)
            path = ROOT / f"docs/mantralia/claridad-{engine}.txt"
            path.write_text(text + "\n")
            print(path)
        return
    script, text = compile_script(args.engine, args.preview)
    output = args.output or ROOT / f"data/mantralia/claridad-podcast-{args.engine}{'-preview' if args.preview else ''}.wav"
    base = args.server.rstrip("/")
    with httpx.Client(timeout=30) as client:
        response = client.get(base + "/profiles")
        response.raise_for_status()
        profile = next((p for p in response.json() if args.profile in (p["id"], p["name"])), None)
        if not profile:
            raise SystemExit("Create a native Latin American voice profile in Voicebox and pass --profile NAME.")
        response = client.post(base + "/generate", json={
            "profile_id": profile["id"], "engine": args.engine, "text": text,
            "language": "es", "speed": script["speed"], "emotion": script.get("emotion", "fluent") if args.engine == "minimax" else None, "pitch": 0,
            "instruct": script["direction"] if args.engine == "fish" else None,
            "personality": False, "normalize": True, "crossfade_ms": 0,
        })
        response.raise_for_status()
        job = response.json()
        print(f"Generation {job['id']} submitted", flush=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get(base + "/history/" + job["id"])
            response.raise_for_status()
            job = response.json()
            if job["status"] == "failed":
                raise SystemExit(f"Generation failed: {job.get('error') or 'See Voicebox history'}")
            if job["status"] == "completed":
                break
            time.sleep(2)
        else:
            raise SystemExit("Still processing. Check Voicebox history before submitting another generation.")
        response = client.get(base + f"/library/{job['id']}/audio")
        response.raise_for_status()
        audio, sample_rate = sf.read(io.BytesIO(response.content), dtype="float32")
        if len(audio) == 0:
            raise SystemExit("The completed generation contained no audio")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        output.with_suffix(".json").write_text(json.dumps({
            "generation_id": job["id"], "profile": profile["name"], "engine": args.engine,
            "duration_sec": len(audio) / sample_rate, "sample_rate": sample_rate,
            "preview": args.preview, "listening_review": "pending",
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"Saved {output} ({len(audio) / sample_rate:.1f}s, {sample_rate} Hz)")


if __name__ == "__main__":
    main()
