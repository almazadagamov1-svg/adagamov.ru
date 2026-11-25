"""Verify the display-only Pages overlay before writing any release file."""
import base64, hashlib, io, json, sys, tarfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parent
SITE=Path(sys.argv[1] if len(sys.argv)>1 else '_site')
BASE=Path(sys.argv[2] if len(sys.argv)>2 else '/tmp/pages-release.tar.gz')
m=json.loads((ROOT/'manifest.json').read_text())
sha=lambda raw:hashlib.sha256(raw).hexdigest()
archive_sha=sha(BASE.read_bytes())

if archive_sha=='b02c8fef40b89b6510e788d9f50fb35714a9a864f68251cca791bd1199c99d5f':
 release=json.loads((SITE/'release.json').read_text())
 index=json.loads((SITE/'data/gvr/map/manifest.json').read_text())
 assert release['releaseId']=='90ed6b4ac66f73b4'
 assert release['gvrSourceDate']==index['sourceDate']=='2026-11-19'
 assert release['gvrSourceSha256']==index['sourceSha256']=='82236a04b36f2a26a6c32f62d7f6334b46b9b7dc071a10d71f8dc4395ec75b0e'
 assert release['torgiSnapshotDate']=='2026-10-01'
 assert index['counts']['records']==51393 and index['counts']['regions']==89
 display=index['displayReconstruction']
 assert display['sourceGeometryChanged'] is False and display['spatialClaim'] is False
 ref=index['files']['reassembledInference']
 assert ref['file']=='/data/gvr/map/inference-reassembled.json'
 raw=(SITE/ref['file'].lstrip('/')).read_bytes()
 assert len(raw)==ref['bytes']==704496
 assert sha(raw)==ref['sha256']=='1b6f219ccda370d06a8d88c2e9c23d5b6c304740e74572288223a11d7db1b111'
 data=json.loads(raw)
 assert data['schema']==4 and data['spatialClaim'] is False
 for key in ('engineSha256','reassemblySha256','registrySha256'):assert data[key]==display[key]
 assert data['counts']==index['counts']['inference']
 assert data['counts']['presentationPolygon']==3037 and data['counts']['holes']==5
 assert data['counts']['reassembledNumberedParts']==8
 print('Verified data and display geometry embedded in release',release['releaseId'])
 from november import apply_overlay
 comparison=apply_overlay(ROOT/'november',SITE,archive_sha)
 print('Verified November display release',comparison['releaseId'],comparison['polygonParts'],'parts;',comparison['newClosedGroups'],'new groups')
 sys.exit(0)

assert m['schema']==1 and m['sourceGeometryChanged'] is False
assert archive_sha==m['baseArchiveSha256']
assert json.loads((SITE/'release.json').read_text())['releaseId']==m['baseRelease']

def allowed(name):
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or str(p)!=name:return False
 return (name.startswith(('_next/static/','karta-gvr/','404/','_not-found/')) or name.startswith('__next.') and name.endswith('.txt') or name in {'404.html','index.html','index.txt','release.json','data/gvr/map/manifest.json','data/gvr/map/inference-reconstructed.json','data/gvr/map/inference-reassembled.json'}) and not name.startswith('karta-gvr/kazan-trial/')

chunks=[]
for e in m['parts']:
 assert PurePosixPath(e['file']).name==e['file']
 raw=(ROOT/e['file']).read_bytes();assert len(raw)==e['bytes'] and sha(raw)==e['sha256'];chunks.append(raw.strip())
archive=base64.b64decode(b''.join(chunks),validate=True)
assert len(archive)==m['archiveBytes'] and sha(archive)==m['archiveSha256']
files={e['file']:e for e in m['files']}
assert len(files)==len(m['files']) and all(allowed(name) for name in files)
pending=[]
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
 members=tar.getmembers();assert len(members)==len(files) and {x.name for x in members}==set(files)
 for x in members:
  assert x.isfile() and allowed(x.name)
  raw=tar.extractfile(x).read();e=files[x.name]
  assert len(raw)==e['bytes'] and sha(raw)==e['sha256'];pending.append((x.name,raw))
for name,raw in pending:
 p=SITE/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
release=json.loads((SITE/'release.json').read_text());assert release==m['release']
index=json.loads((SITE/'data/gvr/map/manifest.json').read_text())
assert index['sourceDate']==release['gvrSourceDate']=='2026-10-22'
assert index['sourceSha256']==release['gvrSourceSha256']
ref=index['files']['reassembledInference'];assert ref['file']=='/data/gvr/map/inference-reassembled.json'
raw=(SITE/ref['file'].lstrip('/')).read_bytes()
assert len(raw)==ref['bytes'] and sha(raw)==ref['sha256']==m['display']['sha256']
data=json.loads(raw);assert data['schema']==4 and data['spatialClaim'] is False
assert data['engineSha256']==m['display']['engineSha256']
assert data['reassemblySha256']==m['display']['reassemblySha256']
assert data['registrySha256']==m['display']['registrySha256']
assert sha((SITE/'data/gvr/map/inference-reconstructed.json').read_bytes())==m['compatibilityArtifactSha256']
assert data['counts']==index['counts']['inference']
assert data['counts']['presentationPolygon']==m['display']['polygons']
assert data['counts']['holes']==m['display']['holes']
assert index['counts']['records']==51149 and index['counts']['regions']==89
assert len(data['records'])==m['display']['records']
for name in ('source','evidence','card-evidence','regions'):assert not (SITE/'data/torgi'/name).exists()
for p in SITE.rglob('*'):
 if p.is_file() and p.suffix in {'.html','.js'}:
  raw=p.read_bytes();assert b'chatgpt.site' not in raw and b'signin-with-chatgpt' not in raw
print('Verified display release',release['releaseId'],m['display']['polygons'],'polygons,',m['display']['holes'],'holes;',len(files),'overlay files')
