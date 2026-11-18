"""Verify and overlay the audited display-only release on the pinned Pages base."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
SITE = Path(sys.argv[1] if len(sys.argv) > 1 else '_site')
BASE = Path(sys.argv[2] if len(sys.argv) > 2 else '/tmp/pages-release.tar.gz')
manifest = json.loads((ROOT / 'manifest.json').read_text())
assert manifest['schema'] == 1 and manifest['sourceGeometryChanged'] is False
assert hashlib.sha256(BASE.read_bytes()).hexdigest() == manifest['baseArchiveSha256']
assert json.loads((SITE / 'release.json').read_text())['releaseId'] == manifest['baseRelease']

def allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name:
        return False
    return (
        name.startswith(('_next/static/', 'karta-gvr/', '404/', '_not-found/'))
        or name.startswith('__next.') and name.endswith('.txt')
        or name in {'404.html', 'index.html', 'index.txt', 'release.json',
                    'data/gvr/map/manifest.json', 'data/gvr/map/inference-reconstructed.json'}
    ) and not name.startswith('karta-gvr/kazan-trial/')

chunks = []
for entry in manifest['parts']:
    assert PurePosixPath(entry['file']).name == entry['file']
    raw = (ROOT / entry['file']).read_bytes()
    assert len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
    chunks.append(raw.strip())
archive = base64.b64decode(b''.join(chunks), validate=True)
assert len(archive) == manifest['archiveBytes']
assert hashlib.sha256(archive).hexdigest() == manifest['archiveSha256']
expected = {entry['file']: entry for entry in manifest['files']}
assert len(expected) == len(manifest['files']) and all(allowed(name) for name in expected)
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
    members = tar.getmembers()
    assert len(members) == len(expected) and {m.name for m in members} == set(expected)
    for member in members:
        assert member.isfile() and allowed(member.name)
        raw = tar.extractfile(member).read()
        entry = expected[member.name]
        assert len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
        target = SITE / member.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
release = json.loads((SITE / 'release.json').read_text())
assert release == manifest['release']
index = json.loads((SITE / 'data/gvr/map/manifest.json').read_text())
assert index['sourceDate'] == release['gvrSourceDate'] == '2026-10-22'
assert index['sourceSha256'] == release['gvrSourceSha256']
ref = index['files']['reconstructedInference']
assert ref['file'] == '/data/gvr/map/inference-reconstructed.json'
raw = (SITE / ref['file'].lstrip('/')).read_bytes()
assert len(raw) == ref['bytes']
assert hashlib.sha256(raw).hexdigest() == ref['sha256'] == manifest['display']['sha256']
data = json.loads(raw)
assert data['schema'] == 3 and data['spatialClaim'] is False
assert index['counts']['inference']['presentationPolygon'] == manifest['display']['polygons'] == 2175
assert index['counts']['inference']['holes'] == manifest['display']['holes'] == 5
assert index['counts']['records'] == 51149 and index['counts']['regions'] == 89
for name in ('source', 'evidence', 'card-evidence', 'regions'):
    assert not (SITE / 'data/torgi' / name).exists()
for path in SITE.rglob('*'):
    if path.is_file() and path.suffix in {'.html', '.js'}:
        raw = path.read_bytes()
        assert b'chatgpt.site' not in raw and b'signin-with-chatgpt' not in raw
print('Verified display reconstruction:', release['releaseId'], '2175 polygons, 5 holes; 33 overlay files')
