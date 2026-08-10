#!/usr/bin/env python3
"""Sync the Voicebox audio library to Cloudflare R2.

Reads the local library API, converts each item to AAC (m4a) and uploads
it to the R2 bucket under ``audio-library/<category>/<slug>.m4a``, plus a
``audio-library/manifest.json`` with public URLs. Incremental: objects
already present in the bucket (same id) are skipped.

Credentials come from backend/.env:
  CLOUDFARE_API_KEY        Cloudflare API token with R2 edit permission
  URL_PUBLIC_DEVELOPMENT   the bucket's public r2.dev URL

Usage:
  python3 scripts/sync-library-r2.py [--api http://127.0.0.1:17493] [--bucket mantralia-audio]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / "backend" / ".env"
CF_API = "https://api.cloudflare.com/client/v4"


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def cf_request(url: str, token: str, method: str = "GET", data: bytes | None = None,
               content_type: str | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return re.sub(r"-+", "-", slug).strip("-")[:60] or "audio"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:17493")
    parser.add_argument("--bucket", default="mantralia-audio")
    parser.add_argument("--prefix", default="audio-library")
    args = parser.parse_args()

    env = load_env()
    token = env.get("CLOUDFARE_API_KEY")
    public_base = (env.get("URL_PUBLIC_DEVELOPMENT") or "").rstrip("/")
    if not token:
        print("CLOUDFARE_API_KEY missing in backend/.env", file=sys.stderr)
        return 1

    _, accounts_raw = cf_request(f"{CF_API}/accounts", token)
    account_id = json.loads(accounts_raw)["result"][0]["id"]
    objects_url = f"{CF_API}/accounts/{account_id}/r2/buckets/{args.bucket}/objects"

    # Existing keys (for incremental sync)
    existing: set[str] = set()
    cursor = ""
    while True:
        url = f"{objects_url}?per_page=500" + (f"&cursor={cursor}" if cursor else "")
        _, listing_raw = cf_request(url, token)
        listing = json.loads(listing_raw)
        for obj in listing.get("result", []):
            existing.add(obj["key"])
        cursor = (listing.get("result_info") or {}).get("cursor") or ""
        if not cursor or not listing.get("result"):
            break

    library = json.loads(urllib.request.urlopen(f"{args.api}/library").read())
    manifest = []
    uploaded = skipped = 0

    with tempfile.TemporaryDirectory() as tmp:
        for item in library["items"]:
            slug = slugify(item["title"].split(",")[0])
            key = f"{args.prefix}/{item['category']}/{slug}-{item['id'][:8]}.m4a"
            public_url = f"{public_base}/{key}" if public_base else None
            manifest.append({
                "id": item["id"],
                "title": item["title"][:120],
                "category": item["category"],
                "duration_sec": item["duration_sec"],
                "url": public_url,
            })
            if key in existing:
                skipped += 1
                continue

            wav = Path(tmp) / f"{item['id']}.wav"
            m4a = Path(tmp) / f"{item['id']}.m4a"
            urllib.request.urlretrieve(f"{args.api}{item['audio_url']}", wav)
            subprocess.run(
                ["afconvert", "-f", "m4af", "-d", "aac", "-b", "192000", str(wav), str(m4a)],
                check=True, capture_output=True,
            )
            status, _ = cf_request(
                f"{objects_url}/{urllib.request.quote(key, safe='')}",
                token, "PUT", m4a.read_bytes(), "audio/mp4",
            )
            if status == 200:
                uploaded += 1
                print(f"↑ {key}")
            else:
                print(f"✗ {key} (HTTP {status})", file=sys.stderr)

    manifest_body = json.dumps(
        {"items": manifest, "total": len(manifest)}, ensure_ascii=False, indent=2
    ).encode()
    cf_request(
        f"{objects_url}/{urllib.request.quote(args.prefix + '/manifest.json', safe='')}",
        token, "PUT", manifest_body, "application/json",
    )

    print(f"\nsubidos: {uploaded} | ya existentes: {skipped} | manifest: {args.prefix}/manifest.json")
    if public_base:
        print(f"manifest público: {public_base}/{args.prefix}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
