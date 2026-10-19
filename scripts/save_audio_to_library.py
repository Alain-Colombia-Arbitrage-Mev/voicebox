"""Import a finished master and verify its exact bytes through the library API.

Reuses a verified receipt on reruns, avoiding duplicate library entries.
"""
import argparse
import hashlib
import json
from pathlib import Path

import httpx


def save(source, title, server):
    source = Path(source).resolve()
    receipt = source.with_suffix('.library.json')
    audio = source.read_bytes()
    digest = hashlib.sha256(audio).hexdigest()
    base = server.rstrip('/')
    with httpx.Client(timeout=120) as client:
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved['sha256'] != digest or saved['title'] != title:
                raise ValueError('Master or title changed; review the existing library receipt before importing again')
            generation_id = saved['generation_id']
        else:
            if '/' in title or '\\' in title:
                raise ValueError('Title must be a single filename stem')
            result = client.post(base + '/generate/import', files={
                'file': (title + source.suffix, audio, 'audio/wav'),
            })
            result.raise_for_status()
            generation_id = result.json()['id']
            # Persist immediately so a failed verification does not duplicate an import.
            saved = {'generation_id': generation_id, 'title': title, 'sha256': digest,
                     'source': str(source), 'verification': 'pending'}
            receipt.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
        library = client.get(base + '/library', params={'search': title})
        library.raise_for_status()
        item = next((item for item in library.json()['items'] if item['id'] == generation_id), None)
        if item is None:
            raise RuntimeError('The imported master is missing from the library')
        result = client.get(base + item['audio_url'])
        result.raise_for_status()
        if hashlib.sha256(result.content).hexdigest() != digest:
            raise RuntimeError('Library download does not match the finished master')
        saved.update({'verification': 'exact_bytes_match', 'library_item': item})
        receipt.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'generation_id': generation_id, 'title': title,
                          'duration_sec': item['duration_sec'], 'verification': saved['verification']},
                         ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--title', required=True)
    parser.add_argument('--server', default='http://127.0.0.1:17493')
    args = parser.parse_args()
    save(args.source, args.title, args.server)
