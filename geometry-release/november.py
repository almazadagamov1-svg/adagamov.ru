"""Build and verify a display-only patch for the pinned November Pages archive."""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import tarfile

import november_revision as revision

ARCHIVE_SHA = 'b02c8fef40b89b6510e788d9f50fb35714a9a864f68251cca791bd1199c99d5f'
SOURCE_SHA = '82236a04b36f2a26a6c32f62d7f6334b46b9b7dc071a10d71f8dc4395ec75b0e'
BASE_RELEASE = '90ed6b4ac66f73b4'
RELEASE = 'release.json'
MANIFEST = 'data/gvr/map/manifest.json'
INDEX = 'data/gvr/map/inference-reassembled.json'
MAP_PAGES = (
    'karta-gvr/index.html',
    'karta-gvr/index.txt',
    'karta-gvr/__next._full.txt',
    'karta-gvr/__next.karta-gvr.__PAGE__.txt',
)
PATCH_FILES = (RELEASE, MANIFEST, INDEX, *MAP_PAGES)
PATCH_ARCHIVE = 'overlay.tar.gz'
PATCH_MANIFEST = 'manifest.json'


def checksum(raw):
    return sha256(raw).hexdigest()


def file_receipt(raw):
    return {'bytes': len(raw), 'sha256': checksum(raw)}


def read_site(site):
    return {name: (site / name).read_bytes() for name in PATCH_FILES}


def release_id(payload):
    hashes = [checksum(payload[name]) for name in (MANIFEST, INDEX)]
    return checksum(('gvr-display-november-v1\n' + '\n'.join(hashes)).encode())[:16]


def update_page_release(raw, name, new_release):
    anchor = br'\"initialSummary\":{\"releaseId\":\"' if name.endswith('.html') else b'"initialSummary":{"releaseId":"'
    old_id = BASE_RELEASE.encode()
    new_id = new_release.encode()
    assert raw.count(old_id) == 1 and raw.count(anchor + old_id) == 1 and new_id not in raw, name
    return raw.replace(anchor + old_id, anchor + new_id, 1)


def group_polygons(records):
    groups = defaultdict(list)
    for record_id, entries in records.items():
        for entry in entries:
            if entry[1] == 'P':
                groups[(record_id, entry[0])].append(entry)
    return groups


def read_index(raw):
    index = json.loads(raw)
    assert index['schema'] == 4 and index['spatialClaim'] is False
    assert index['sourceSha256'] == SOURCE_SHA
    records = dict(index['records'])
    assert len(records) == len(index['records'])
    assert all(isinstance(record_id, str) for record_id in records)
    totals = Counter()
    groups = {'P': set(), 'O': set(), 'N': set()}
    holes = 0
    for record_id, entries in records.items():
        assert entries, (record_id, 'empty entry list')
        for entry in entries:
            group, kind, indexes, segments, jumps, method, *_ = entry
            assert 6 <= len(entry) <= 9 and type(group) is int and group >= 0
            assert kind in groups and method in index['methods']
            assert isinstance(indexes, list) and isinstance(segments, list) and type(jumps) is int
            totals[kind] += 1
            groups[kind].add((record_id, group))
            if kind == 'P' and len(entry) > 6:
                holes += len(entry[6])
    counts = index['counts']
    assert counts['presentationEntries'] == totals.total()
    for kind, name in zip(('P', 'O', 'N'), ('Polygon', 'Open', 'PointsOnly')):
        assert counts['presentation' + name] == totals[kind]
    assert counts['polygon'] == len(groups['P'])
    assert counts['open'] == len(groups['O'] - groups['P'])
    assert counts['eligibleGroups'] == len(set.union(*groups.values()))
    assert counts['pointsOnly'] == counts['universeGroups'] - counts['polygon'] - counts['open']
    assert counts['holes'] == holes
    return index, records


def validate_pair(base, candidate, revision_records=()):
    before_release, after_release = (json.loads(site[RELEASE]) for site in (base, candidate))
    assert before_release['releaseId'] == BASE_RELEASE
    assert before_release['gvrSourceDate'] == '2026-11-19'
    assert before_release['gvrSourceSha256'] == SOURCE_SHA
    assert before_release['torgiSnapshotDate'] == '2026-10-01'
    assert after_release == {**before_release, 'releaseId': release_id(candidate)}
    assert after_release['releaseId'] != BASE_RELEASE
    for name in MAP_PAGES:
        assert candidate[name] == update_page_release(base[name], name, after_release['releaseId']), name

    before_map, after_map = (json.loads(site[MANIFEST]) for site in (base, candidate))
    old_index, old_records = read_index(base[INDEX])
    new_index, new_records = read_index(candidate[INDEX])
    assert before_map['counts']['records'] == 51393 and before_map['counts']['regions'] == 89
    for site, manifest, index in ((base, before_map, old_index), (candidate, after_map, new_index)):
        assert manifest['sourceDate'] == before_release['gvrSourceDate']
        assert manifest['sourceSha256'] == SOURCE_SHA
        assert manifest['counts']['inference'] == index['counts']
        assert manifest['files']['reassembledInference'] == {'file': '/' + INDEX, **file_receipt(site[INDEX])}
        display = manifest['displayReconstruction']
        assert display['sourceGeometryChanged'] is False and display['spatialClaim'] is False
        for key in ('engine', 'engineSha256', 'reassemblySha256', 'registrySha256'):
            assert display[key] == index[key]
            if key != 'engine':
                assert re.fullmatch(r'[a-f0-9]{64}', display[key])
    assert before_map['counts']['inference']['presentationPolygon'] == 3037

    expected_map = deepcopy(before_map)
    expected_map['counts']['inference'] = after_map['counts']['inference']
    expected_map['files']['reassembledInference'] = after_map['files']['reassembledInference']
    for key in ('engineSha256', 'reassemblySha256'):
        expected_map['displayReconstruction'][key] = after_map['displayReconstruction'][key]
    helper_signature = new_index.get('wgsSectionsSha256')
    if helper_signature is not None:
        assert re.fullmatch(r'[a-f0-9]{64}', helper_signature)
        expected_map['displayReconstruction']['wgsSectionsSha256'] = helper_signature
    assert expected_map == after_map, 'A protected map manifest field changed'
    assert all(new_index[key] == old_index[key] for key in ('engine', 'fields', 'indexScope'))
    assert new_index['methods'].keys() == old_index['methods'].keys(), 'Unknown client display method'
    assert all(new_index['counts'][key] == old_index['counts'][key] for key in ('universeGroups', 'eligibleGroups'))

    before_polygons = group_polygons(old_records)
    after_polygons = group_polygons(new_records)
    original_changes = {group for group, entries in before_polygons.items() if after_polygons.get(group) != entries}
    assert all(record_id in revision_records for record_id, _ in original_changes), \
        'Previously published calculated polygon changed outside certified records'
    assert revision_records or len(after_polygons) > len(before_polygons), 'Patch contains no additional closed groups'
    return {
        'releaseId': after_release['releaseId'],
        'newClosedGroups': len(after_polygons.keys() - before_polygons.keys()),
        'unchangedClosedGroups': len(before_polygons) - len(original_changes),
        'polygonParts': new_index['counts']['presentationPolygon'],
        'polygonRecords': len({record_id for record_id, _ in after_polygons}),
        'holes': new_index['counts']['holes'],
        'files': {name: file_receipt(candidate[name]) for name in PATCH_FILES},
    }


def safe_archive(candidate):
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name in PATCH_FILES:
            info = tarfile.TarInfo(name)
            info.size = len(candidate[name])
            info.mode = 0o644
            tar.addfile(info, BytesIO(candidate[name]))
    return gzip.compress(archive.getvalue(), compresslevel=9, mtime=0)


def pack(baseline, staged, destination, revision_ids=None, previous_package=None):
    base = read_site(baseline)
    candidate = {name: (staged / name).read_bytes() for name in (MANIFEST, INDEX)}
    release = {**json.loads(base[RELEASE]), 'releaseId': release_id(candidate)}
    candidate[RELEASE] = (json.dumps(release, indent=2) + '\n').encode()
    for name in MAP_PAGES:
        candidate[name] = update_page_release(base[name], name, release['releaseId'])
    certificate_raw = None
    if revision_ids is not None:
        assert previous_package is not None
        prior_meta = (previous_package / PATCH_MANIFEST).read_bytes()
        prior_archive = (previous_package / PATCH_ARCHIVE).read_bytes()
        prior = read_predecessor(base, prior_meta, prior_archive)
        certificate = revision.certificate(base[INDEX], prior[INDEX], candidate[INDEX],
                                           revision_ids, baseline, read_index, SOURCE_SHA)
        certificate_raw = (json.dumps(certificate, indent=2) + '\n').encode()
    comparison = validate_pair(base, candidate, set(revision_ids or []))
    archive = safe_archive(candidate)
    metadata = {
        'schema': 1,
        'baseArchiveSha256': ARCHIVE_SHA,
        'baseRelease': BASE_RELEASE,
        'sourceSha256': SOURCE_SHA,
        'baseFiles': {name: file_receipt(raw) for name, raw in base.items()},
        'archive': file_receipt(archive),
        'comparison': comparison,
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / PATCH_ARCHIVE).write_bytes(archive)
    if certificate_raw is not None:
        metadata['revisionCertificate'] = file_receipt(certificate_raw)
        (destination / revision.CERTIFICATE).write_bytes(certificate_raw)
        (destination / revision.PREVIOUS_MANIFEST).write_bytes(prior_meta)
        (destination / revision.PREVIOUS_ARCHIVE).write_bytes(prior_archive)
    (destination / PATCH_MANIFEST).write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def read_archive(metadata, raw):
    assert file_receipt(raw) == metadata['archive']
    candidate = {}
    with tarfile.open(fileobj=BytesIO(raw), mode='r:gz') as tar:
        members = tar.getmembers()
        assert len(members) == len(PATCH_FILES) and {member.name for member in members} == set(PATCH_FILES)
        for member in members:
            assert member.isfile() and member.size == metadata['comparison']['files'][member.name]['bytes']
            candidate[member.name] = tar.extractfile(member).read()
    return candidate


def read_predecessor(base, metadata_raw, archive_raw):
    assert checksum(metadata_raw) == revision.PREVIOUS_MANIFEST_SHA
    assert checksum(archive_raw) == revision.PREVIOUS_ARCHIVE_SHA
    metadata = json.loads(metadata_raw)
    assert metadata['schema'] == 1 and metadata['baseArchiveSha256'] == ARCHIVE_SHA
    assert {name: file_receipt(raw) for name, raw in base.items()} == metadata['baseFiles']
    previous = read_archive(metadata, archive_raw)
    assert json.loads(previous[RELEASE])['releaseId'] == revision.PREVIOUS_RELEASE
    assert validate_pair(base, previous) == metadata['comparison']
    return previous


def read_overlay(directory, site, archive_sha):
    metadata = json.loads((directory / PATCH_MANIFEST).read_bytes())
    assert metadata['schema'] == 1
    assert archive_sha == metadata['baseArchiveSha256'] == ARCHIVE_SHA
    assert metadata['baseRelease'] == BASE_RELEASE and metadata['sourceSha256'] == SOURCE_SHA
    base = read_site(site)
    assert {name: file_receipt(raw) for name, raw in base.items()} == metadata['baseFiles']
    candidate = read_archive(metadata, (directory / PATCH_ARCHIVE).read_bytes())
    ids = []
    if 'revisionCertificate' in metadata:
        certificate_raw = (directory / revision.CERTIFICATE).read_bytes()
        assert file_receipt(certificate_raw) == metadata['revisionCertificate']
        declared = json.loads(certificate_raw)
        previous = read_predecessor(base, (directory / revision.PREVIOUS_MANIFEST).read_bytes(),
                                    (directory / revision.PREVIOUS_ARCHIVE).read_bytes())
        ids = [row['recordId'] for row in declared['revisionRecords']]
        checked = revision.certificate(base[INDEX], previous[INDEX], candidate[INDEX], ids, site, read_index, SOURCE_SHA)
        assert checked == declared, 'Full-source correction certificate mismatch'
    comparison = validate_pair(base, candidate, set(ids))
    assert comparison == metadata['comparison']
    return comparison, candidate


def apply_overlay(directory, site, archive_sha):
    comparison, candidate = read_overlay(directory, site, archive_sha)
    for name in PATCH_FILES:
        (site / name).write_bytes(candidate[name])
    return comparison


def diff_tree(before, after, package=None):
    def checksums(root):
        return {p.relative_to(root).as_posix(): checksum(p.read_bytes())
                for p in root.rglob('*') if p.is_file()}

    old = checksums(before)
    new = checksums(after)
    assert old.keys() == new.keys(), 'The static release file inventory changed'
    changed = sorted(name for name, digest in old.items() if new[name] != digest)
    assert changed == sorted(PATCH_FILES), changed
    if package is None:
        comparison = validate_pair(read_site(before), read_site(after))
    else:
        comparison, candidate = read_overlay(package, before, ARCHIVE_SHA)
        assert read_site(after) == candidate, 'Applied site bytes differ from the certified overlay'
    return {**comparison, 'protectedFilesUnchanged': len(old) - len(changed), 'changedFiles': changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    packer = commands.add_parser('pack')
    packer.add_argument('baseline', type=Path)
    packer.add_argument('staged', type=Path)
    packer.add_argument('package', type=Path)
    packer.add_argument('--revision-ids', type=Path)
    packer.add_argument('--predecessor-package', type=Path)
    apply = commands.add_parser('apply')
    apply.add_argument('package', type=Path)
    apply.add_argument('site', type=Path)
    apply.add_argument('baseline_archive', type=Path)
    audit = commands.add_parser('audit')
    audit.add_argument('baseline', type=Path)
    audit.add_argument('patched', type=Path)
    audit.add_argument('--package', type=Path)
    args = parser.parse_args()
    if args.command == 'pack':
        assert bool(args.revision_ids) == bool(args.predecessor_package), 'Both revision inputs are required'
        ids = json.loads(args.revision_ids.read_text()) if args.revision_ids else None
        result = pack(args.baseline, args.staged, args.package, ids, args.predecessor_package)
    elif args.command == 'apply':
        result = apply_overlay(args.package, args.site, checksum(args.baseline_archive.read_bytes()))
    else:
        result = diff_tree(args.baseline, args.patched, args.package)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
