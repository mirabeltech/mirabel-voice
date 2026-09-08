"""Prepare an approval manifest entry locally; publishing it is a release action.

Contains only artifact name, version and hash, never the private bundle settings.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def approve(bundle: Path, manifest: Path):
    match = re.fullmatch(r'MirabelVoice-(\d+\.\d+\.\d+)-python\.zip', bundle.name)
    if not match:
        raise ValueError('Expected a versioned Python bundle ZIP')
    data = json.loads(manifest.read_text()) if manifest.exists() else {'schema': 1, 'bundles': []}
    if data.get('schema') != 1:
        raise ValueError('Unsupported manifest schema')
    with bundle.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    entry = {'filename': bundle.name, 'version': match[1], 'sha256': digest, 'approved': True}
    data['bundles'] = [e for e in data['bundles'] if e['sha256'] != digest] + [entry]
    manifest.write_text(json.dumps(data, indent=2) + '\n')
    return entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--manifest', type=Path, default=Path('packaging/bundles.json'))
    args = parser.parse_args()
    print(json.dumps(approve(args.bundle, args.manifest), indent=2))
