"""Verify a complete Pages build whose sole data addition is the Kazan history layer."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re

ARCHIVE_PATH = 'data/archives/kazan-vodokanal-2026-10-22.json'
ARCHIVE_SOURCE_SHA = 'a59a22d8fe99f31fdc2571d78df1b356be8f0aec0e0ab4280066e1e0574c19ff'
ACTIVE_SOURCE_SHA = '82236a04b36f2a26a6c32f62d7f6334b46b9b7dc071a10d71f8dc4395ec75b0e'
PREDECESSOR_RELEASE = 'e4c62b86b22a7c4d'
PROTECTED_DATA = {'files': 2059, 'sha256': 'b422ed67a26142d4c5a50dd74f157b353ce6945e146bac5834e099c037064679'}
RELEASE_PAGES = ('karta-gvr/index.html', 'karta-gvr/index.txt', 'karta-gvr/__next._full.txt',
                 'karta-gvr/__next.karta-gvr.__PAGE__.txt')
ARCHIVE_RECORD_FIELDS = {'id', 'waterObject', 'purpose', 'endDate', 'sourceRow', 'shapes'}
ARCHIVE_SHAPE_FIELDS = {'type', 'coordinates', 'holes', 'calculated'}
ACTIVE_COUNTS = {'sourceRecords': 51394, 'records': 51393, 'pass': 47822, 'hints': 3571, 'regions': 89}
EDGE_TYPES = {'polygon', 'line', 'point', 'multi_point'}


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    checksum = sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def receipt(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def protected_data(site):
    files = sorted((f.relative_to(site).as_posix(), sha(f)) for f in (site/'data').rglob('*')
                   if f.is_file() and f.relative_to(site).as_posix() not in {ARCHIVE_PATH, 'data/verification.json'})
    return {'files': len(files), 'sha256': sha256(json.dumps(files, separators=(',', ':')).encode()).hexdigest()}


def coordinate(point):
    return (isinstance(point, list) and len(point) == 2 and all(type(x) in (int, float) and isfinite(x) for x in point)
            and -180 <= point[0] <= 180 and -90 <= point[1] <= 90)


def summarize_history(payload):
    assert set(payload) == {'sourceDate', 'sourceSha256', 'sourceRelease', 'spatialClaim', 'region', 'holder', 'inn', 'records'}
    assert payload['sourceDate'] == '2026-10-22' and payload['sourceSha256'] == ARCHIVE_SOURCE_SHA
    assert re.fullmatch(r'[a-f0-9]{16}', payload['sourceRelease'])
    assert payload['spatialClaim'] is False and payload['region'] == 'Республика Татарстан'
    assert payload['inn'] == '1653006666' and isinstance(payload['holder'], str) and payload['holder'].strip()
    records = payload['records']
    assert isinstance(records, list) and len(records) == 15
    ids = set()
    rows = set()
    parts = Counter()
    for row in records:
        assert set(row) == ARCHIVE_RECORD_FIELDS
        assert isinstance(row['id'], str) and row['id'] and row['id'] not in ids
        assert type(row['sourceRow']) is int and row['sourceRow'] > 0 and row['sourceRow'] not in rows
        assert all(isinstance(row[key], str) for key in ('waterObject', 'purpose', 'endDate'))
        ids.add(row['id'])
        rows.add(row['sourceRow'])
        assert isinstance(row['shapes'], list)
        for shape in row['shapes']:
            assert set(shape) <= ARCHIVE_SHAPE_FIELDS and shape['type'] in EDGE_TYPES
            assert 'calculated' not in shape or type(shape['calculated']) is bool
            points = shape['coordinates']
            assert isinstance(points, list) and points and all(coordinate(point) for point in points)
            kind = shape['type']
            if kind == 'point':
                assert len(points) == 1
            elif kind in {'line', 'multi_point'}:
                assert len(points) >= 2
            else:
                assert len({tuple(point) for point in points}) >= 3
            for ring in shape.get('holes', []):
                assert kind == 'polygon' and len({tuple(point) for point in ring}) >= 3 and all(coordinate(point) for point in ring)
            parts[kind] += 1
    assert parts, 'Kazan history layer lacks geometry'
    return {'sourceDate': payload['sourceDate'], 'sourceSha256': payload['sourceSha256'],
            'sourceRelease': payload['sourceRelease'], 'records': len(records), 'parts': dict(parts)}


def verify_site(site):
    checksum = protected_data(site)
    assert checksum == PROTECTED_DATA, 'The active public data tree differs from release e4c62b86b22a7c4d'
    release = read(site/'release.json')
    release_id = release['releaseId']
    assert re.fullmatch(r'[a-f0-9]{16}', release_id) and release_id != PREDECESSOR_RELEASE
    assert release == {'schema': 1, 'releaseId': release_id, 'gvrSourceDate': '2026-11-19',
                       'gvrSourceSha256': ACTIVE_SOURCE_SHA, 'torgiSnapshotDate': '2026-10-01'}
    assert all((site / name).read_bytes().count(release_id.encode()) == 1 for name in RELEASE_PAGES)
    assert any(('/' + ARCHIVE_PATH).encode() in chunk.read_bytes()
               for chunk in (site/'_next/static/chunks').glob('*.js')), 'Built map does not load the history dataset'
    gvr_map = read(site/'data/gvr/map/manifest.json')
    assert {key:gvr_map['counts'][key] for key in ACTIVE_COUNTS} == ACTIVE_COUNTS
    assert gvr_map['counts']['inference']['presentationPolygon'] == 3688
    assert read(site/'data/verification.json')
    historical_layer = site/ARCHIVE_PATH
    return {'release': release, 'gvrCounts': ACTIVE_COUNTS, 'protectedData': checksum,
            'history': {'path': ARCHIVE_PATH, **receipt(historical_layer), **summarize_history(read(historical_layer))}}


def build_manifest(site, archive):
    assert archive.is_file()
    return {'schema': 1, 'kind': 'kazan-vodokanal-history-full-site', 'predecessorReleaseId': PREDECESSOR_RELEASE,
            'archive': receipt(archive), **verify_site(site)}


def verify_for_pages(site, archive, metadata_path):
    declared = read(metadata_path)
    assert build_manifest(site, archive) == declared, 'Kazan history full-build receipt mismatch'
    return declared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('site', type=Path)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    data = (verify_for_pages(args.site, args.archive, args.manifest) if args.manifest else
            build_manifest(args.site, args.archive))
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
