"""Install a repository voice bundle into a running Voicebox, without API charges."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "assets/voices/deseos-timbre-calido-variante-2"


def install(bundle: Path, server: str):
    bundle = bundle.resolve()
    spec = json.loads((bundle / "voice.json").read_text())
    files = {}
    for field in ("reference_file", "preview_file"):
        path = (bundle / spec[field]).resolve()
        if path.parent != bundle:
            raise ValueError("Voice audio must be inside its bundle")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != spec["sha256"][path.name]:
            raise ValueError(f"Checksum mismatch: {path.name}")
        audio, rate = sf.read(io.BytesIO(data))
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError(f"Invalid audio: {path.name}")
        if field == "reference_file" and not 10 <= len(audio) / rate <= 30:
            raise ValueError("Cloning reference must last 10–30 seconds")
        files[field] = data

    with httpx.Client(base_url=server.rstrip("/"), timeout=180) as client:
        def get(path, **kwargs):
            r = client.get(path, **kwargs)
            r.raise_for_status()
            return r.json()

        profile = next((p for p in get("/profiles") if p["name"] == spec["name"]), None)
        created = profile is None
        if created:
            r = client.post("/profiles", json={key: spec[key] for key in
                ("name", "description", "language", "voice_type", "default_engine")})
            r.raise_for_status()
            profile = r.json()
        elif any(profile.get(key) != spec[key] for key in
                 ("voice_type", "language", "default_engine", "description")):
            raise ValueError("A different voice already uses this bundle's name")
        pid = profile["id"]
        samples = get(f"/profiles/{pid}/samples")
        if not samples:
            r = client.post(f"/profiles/{pid}/samples",
                data={"reference_text": spec["reference_text"]},
                files={"file": (spec["reference_file"], files["reference_file"], "audio/wav")})
            r.raise_for_status()
            samples = [r.json()]
            r = client.put(f"/profiles/{pid}/effects", json={"effects_chain": []})
            r.raise_for_status()
        if len(samples) != 1 or samples[0]["reference_text"] != spec["reference_text"]:
            raise ValueError("Existing profile samples differ from the voice bundle")

        delivery = {key: spec[key] for key in
                    ("default_emotion", "default_speed", "default_pitch") if key in spec}
        if delivery:
            payload = {key: profile.get(key) for key in
                       ("name", "description", "language", "default_engine", "personality")}
            r = client.put(f"/profiles/{pid}", json={**payload, **delivery})
            r.raise_for_status()
            if any(r.json().get(key) != value for key, value in delivery.items()):
                raise RuntimeError("The server did not preserve the bundle's delivery settings; update Voicebox first")

        # Reuse the audio already saved during creation of the variant.
        items = get("/library", params={"search": spec["name"], "include_voices": True})["items"]
        matching = [item for item in items if item["title"] == spec["name"] or
                    (item.get("voice") == spec["name"] and item["title"] == spec.get("preview_text", "")[:200])]
        item = None
        for candidate in matching:
            r = client.get(candidate["audio_url"])
            r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest() == spec["sha256"][spec["preview_file"]]:
                item = candidate
                break
        if item is None:
            preview, rate = sf.read(io.BytesIO(files["preview_file"]))
            manifest = {"version": "1.0", "profile": {"name": spec["name"]}, "generation": {
                "text": spec.get("preview_text", spec["name"]), "language": spec["language"],
                "duration": len(preview) / rate, "engine": spec["default_engine"],
                "emotion": spec.get("default_emotion"), "speed": spec.get("default_speed"),
                "pitch": spec.get("default_pitch"),
            }}
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("manifest.json", json.dumps(manifest))
                zipped.writestr("audio/preview.wav", files["preview_file"])
            r = client.post("/history/import", files={"file": ("preview.zip", archive.getvalue(), "application/zip")})
            r.raise_for_status()
            gid = r.json()["id"]
            item = next(i for i in get("/library", params={"search": spec["name"], "include_voices": True})["items"]
                        if i["id"] == gid)
        r = client.get(item["audio_url"])
        r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest() != spec["sha256"][spec["preview_file"]]:
            raise RuntimeError("Library audio does not match the bundled preview")
        verified_samples = get(f"/profiles/{pid}/samples")
        if len(verified_samples) != 1 or verified_samples[0]["id"] != samples[0]["id"]:
            raise RuntimeError("Voice reference was not persisted")
    result = {"name": spec["name"], "profile_id": pid, "profile_created": created,
              "generation_id": item["id"], "sample_id": samples[0]["id"],
              "library_verification": "exact_bytes_match", "provider_api_called": False}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--server", default="http://127.0.0.1:17493")
    args = parser.parse_args()
    install(args.bundle, args.server)
