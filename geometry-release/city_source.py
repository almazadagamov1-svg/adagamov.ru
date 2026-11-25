"""Verify the full Moscow and Saint Petersburg build, preserving the Kazan history layer."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from kazan_archive import ARCHIVE_PATH, RELEASE_PAGES, receipt, sha, summarize_history

SOURCE_SHA = '82236a04b36f2a26a6c32f62d7f6334b46b9b7dc071a10d71f8dc4395ec75b0e'
OLD_RELEASE = '9a2371739caaaf4a'
OLD_ARCHIVE_SHA = 'effa6da6ad7755b185b5a39f0f529c6e12af7d4f19e8287013da6d77fbeb926c'
KAZAN_SHA = '43d6e87801edb77eb11c492d34c77366d1d3102576a1725617b05ba88f86baad'
REVIEW_SHA = 'ce16cdda321c980a12d5f0315929878d4eca75d13ed0d18ec7d8959d96aa261a'
OLD_LEDGER_SHA = 'ae178acc22631857616e3bff24ecb151dbe9e4ffab37e8496aa55a18638b5ceb'
LITERAL_SHA = '70825069eaee5bbb5aba2efed802509772d82bdf82c6e25fc7baca568a578bf5'
COUNTS = {'sourceRecords': 51394, 'records': 51393, 'duplicatesSuppressed': 1,
          'pass': 47903, 'hints': 3490, 'regions': 89}
REGIONS = {'Москва': 54, 'Санкт-Петербург': 27}
GROUPS = {'point': 67, 'multi_point': 26, 'line': 18, 'polygon': 8}
SOURCE_FIELDS = ('id', 'r', 'b', 'h', 'i', 'o', 'c', 'p', 'e', 'l', 'sw', 'd')
PROVENANCE_FIELDS = ('sourceSheet', 'sourceRow', 'recordKey', 'sourcePayloadHash')
GEOMETRY_PROVENANCE_FIELDS = ('axisBasis', 'axisOrder', 'geometrySha256', 'partialSource', 'resolvedCrs', 'sourceCrs', 'transformId')
SEARCH_FIELDS = ('id', 'region', 'holder', 'waterObject', 'waterCode', 'endDate')

# These digests are from the byte-verified deployed 9a2371739caaaf4a archive,
# except for the expected 81 payloads, which come from the independent review.
EXPECTED = {'stableSourceManifest': '50de06b8f289f26fbf0bdfa97950a45d7107386a8c8ed6fcce7b0cee30310010',
 'oldCoordinateRecords': '824824bd85b027de704fcc1d34ef85ebc35b442296efb89f6b41d20f30e439f4',
 'unresolvedRecords': '615c2fd0a1d92b488069cd9ebedd1f4a99908a3913efd8dcd211ecdcd962bc99',
 'promotedRowsSourceMetadata': 'c50e98101c8fcf4ea0855ab6b8d671b2ae9c002cec85ba10ecf19b6bf7a2fced',
 'allSearchMetadata': 'fa84eac43a865ed1060dccea3d3b02a4dae5cb5862cf3e96d7adbb566322dfec',
 'oldSearchPlacement': 'ab69aaf02d765307db00c7d6bfcdb10c6bc0a012fe4486635f465ac7454f87a8',
 'oldLegacyCalculatedEntries': '9c18f790053708340cd05b358506d6c4a64b633ac8b0e597ad6bb92afcc94ea5',
 'oldCalculatedEntries': 'a54b4c7b4ba369f27cd9803c6337624eda9836bae8289896a25b63cbf1984825',
 'protectedData': {'files': 78, 'sha256': '17c1d3859824137dbd0ab541064284c90d274ec4ac661d8a2742588b08366249'},
 'cityIdSet': 'c8c878bf4c36c70dce8fe791179e8308dca004d36651d40b1b7f34c42a02466b',
 'cityGeometryPayloads': '825723763a30d07a5df34590732d5a5feeda333a57a9bcb5b238b160531f6368'}


def canon(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()


def digest(value):
    return sha256(canon(value)).hexdigest()


def read(path, declared=None):
    raw = path.read_bytes()
    if declared is not None:
        assert {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()} == {
            key:declared[key] for key in ('bytes', 'sha256')}, path.name
    return json.loads(raw)


def public_file(site, path):
    assert isinstance(path, str) and path.startswith('/data/gvr/') and '..' not in Path(path).parts
    return site / path[1:]


def tile_rows(site, entries):
    output = {}
    membership = {}
    for key, item in entries.items():
        rows = read(public_file(site, item['file']), item)
        assert isinstance(rows, list) and len(rows) == item['count'], item['file']
        for row in rows:
            ident = row['id']
            assert ident not in output or output[ident] == row, ident
            output[ident] = row
            membership.setdefault(ident, set()).add(key)
    return output, membership


def search_rows(site, declared, tiles, memberships, unresolved):
    records = {}
    for shard in declared.values():
        payload = read(public_file(site, shard['file']), shard)
        assert payload['region'] == shard['name'] and len(payload['records']) == shard['count']
        for compact in payload['records']:
            row = dict(zip(payload['fields'], compact, strict=True))
            ident = row['id']
            assert ident not in records and row['region'] == shard['name']
            if ident in tiles:
                assert row['status'] == 'P' and row['tile'] in memberships[ident]
            else:
                assert ident in unresolved and row['status'] == 'H'
            records[ident] = row
    assert records.keys() == tiles.keys() | unresolved.keys()
    return records


def concordance(site):
    gvr = site / 'data/gvr'
    assert {p.name for p in gvr.iterdir()} == {'manifest.json', 'map', 'tiles', 'unresolved-regions'}
    source = read(gvr/'manifest.json')
    map_ = read(gvr/'map/manifest.json')
    assert source['sourceDate'] == map_['sourceDate'] == '2026-11-19'
    assert source['sourceSha256'] == map_['sourceSha256'] == SOURCE_SHA
    tiles, memberships = tile_rows(site, source['tiles'])
    unresolved, _ = tile_rows(site, source['textShards'])
    assert not tiles.keys() & unresolved.keys()
    assert len(tiles) == source['recordsWithCoordinates'] == map_['counts']['pass']
    assert len(unresolved) == source['recordsWithoutCoordinates'] == map_['counts']['hints']
    assert len(tiles) + len(unresolved) == source['records'] == map_['counts']['records'] == 51393
    file = map_['files']['hints']
    hints = read(public_file(site, file['file']), file)
    assert hints['spatialClaim'] is False
    hint_rows = {row['id']:row for row in hints['records']}
    assert len(hint_rows) == len(hints['records']) and hint_rows.keys() == unresolved.keys()
    assert all(row['spatialClaim'] is False and not row.get('g') for row in hint_rows.values())
    search = search_rows(site, map_['files']['searchShards'], tiles, memberships, unresolved)
    overview_ref = map_['files']['overview']
    read(public_file(site, overview_ref['file']), overview_ref)
    for key in ('inference', 'reassembledInference'):
        ref = map_['files'][key]
        index = read(public_file(site, ref['file']), ref)
        assert index['spatialClaim'] is False
        if key == 'inference':
            assert index['schema'] == 2 and index['counts'] == map_['counts']['legacyInference']
            legacy = dict(index['records'])
            assert len(legacy) == len(index['records']) and legacy.keys() <= tiles.keys()
        else:
            assert index['sourceSha256'] == SOURCE_SHA
            assert index['schema'] == 4 and index['counts'] == map_['counts']['inference']
            assert map_['displayReconstruction']['sourceGeometryChanged'] is False
            assert all(map_['displayReconstruction'][k] == index[k] for k in (
                'engineSha256', 'reassemblySha256', 'registrySha256', 'wgsSectionsSha256'))
            display = dict(index['records'])
            assert len(display) == len(index['records']) and display.keys() <= tiles.keys()
    return source, map_, tiles, unresolved, hint_rows, search, display, legacy


def source_metadata(row):
    return [row.get(key) for key in SOURCE_FIELDS] + [row['v'].get(key) for key in PROVENANCE_FIELDS]


def geometry_metadata(row):
    return [row.get('g'), row.get('w'), *(row['v'].get(key) for key in GEOMETRY_PROVENANCE_FIELDS)]


def static_non_gvr_data(site):
    files = sorted((f.relative_to(site).as_posix(), sha(f)) for f in (site/'data').rglob('*') if f.is_file()
                   and not f.relative_to(site).as_posix().startswith('data/gvr/')
                   and f.relative_to(site).as_posix() != 'data/verification.json')
    return {'files':len(files), 'sha256':digest(files)}


def protected_projections(state, site, upgraded):
    source, map_, tiles, unresolved, hints, search, display, legacy = state
    stable_source = {key:source[key] for key in ('sourceDate', 'sourceSha256', 'sourceUrl', 'sourceQuality',
                                                 'sourceRecords', 'records', 'duplicatesSuppressed')}
    stable_source['regions'] = sorted((row['name'], row['records']) for row in source['regions'])
    return {
        'stableSourceManifest': digest(stable_source),
        'oldCoordinateRecords': digest([(ident, source_metadata(row), geometry_metadata(row))
                                        for ident, row in sorted(tiles.items()) if ident not in upgraded]),
        'unresolvedRecords': digest([(ident, source_metadata(row), hints[ident]['q'])
                                      for ident, row in sorted(unresolved.items()) if ident not in upgraded]),
        'promotedRowsSourceMetadata': digest([(ident, source_metadata(tiles[ident] if ident in tiles else unresolved[ident]))
                                             for ident in sorted(upgraded)]),
        'allSearchMetadata': digest([(ident, [row.get(key) for key in SEARCH_FIELDS]) for ident, row in sorted(search.items())]),
        'oldSearchPlacement': digest([(ident, search[ident]) for ident in sorted(tiles) if ident not in upgraded]),
        'oldLegacyCalculatedEntries': digest([(ident, entries) for ident, entries in sorted(legacy.items()) if ident not in upgraded]),
        'oldCalculatedEntries': digest([(ident, entries) for ident, entries in sorted(display.items()) if ident not in upgraded]),
        'protectedData': static_non_gvr_data(site),
    }


def geometry_payload(row):
    prov = row['v']
    return [row['id'], row['r'], prov['sourceRow'], prov['sourcePayloadHash'], row['g'], row['w'],
            [prov.get(key) for key in GEOMETRY_PROVENANCE_FIELDS]]


def payload_from_review(item):
    row, resolution = item['row'], item['after']
    semantics = {'point': 'none', 'multi_point': 'none', 'line': 'source_ordered_open_sequence', 'polygon': 'source_closed_ring'}
    public_groups = [dict(type=group['type'], coordinates=[[lon, lat] for lat, lon in group['coordinates']],
                          reason=group['reason'], degraded=group['degraded'], edgeSemantics=semantics[group['type']])
                     for group in resolution['groups']]
    return [row['record_id'], row['region'], row['source_row'], row['source_payload_hash'], public_groups,
            resolution['warning'], [resolution.get(key) for key in GEOMETRY_PROVENANCE_FIELDS]]


def derive_expected(site, baseline_archive, independent_review):
    assert sha(baseline_archive) == OLD_ARCHIVE_SHA and read(site/'release.json')['releaseId'] == OLD_RELEASE
    assert sha(independent_review) == REVIEW_SHA
    data = read(independent_review)
    expected = {item['row']['record_id']:item for item in data['accepted']}
    assert len(expected) == len(data['accepted']) == 81 and not data['anomalies']
    state = concordance(site)
    assert expected.keys() <= state[3].keys()
    return {**protected_projections(state, site, expected), 'cityIdSet': digest(sorted(expected)),
            'cityGeometryPayloads': digest([payload_from_review(item) for _, item in sorted(expected.items())])}


def evidence_summary(data):
    assert data['schema'] == 1 and data['sourceSha256'] == SOURCE_SHA
    assert data['previousRecordsSha256'] == OLD_LEDGER_SHA
    assert data['candidateAuditSha256'] == REVIEW_SHA and data['literalVerificationSha256'] == LITERAL_SHA
    assert data['unchangedRecords'] == 51313
    assert re.fullmatch(r'[a-f0-9]{64}', data['recordsSha256']) and re.fullmatch(r'[a-f0-9]{64}', data['manifestSha256'])
    rows = data['upgradedRows']
    ids = sorted(row['id'] for row in rows)
    assert len(ids) == len(set(ids)) == 81 and digest(ids) == EXPECTED['cityIdSet']
    assert Counter(row['region'] for row in rows) == REGIONS
    return ids, {'ledgerSha256': data['recordsSha256'], 'ledgerManifestSha256': data['manifestSha256']}


def verify_site(site, ids, evidence):
    assert isinstance(ids, list) and len(ids) == len(set(ids)) == 81 and ids == sorted(ids)
    assert digest(ids) == EXPECTED['cityIdSet']
    release = read(site/'release.json')
    release_id = release['releaseId']
    assert re.fullmatch(r'[a-f0-9]{16}', release_id) and release_id != OLD_RELEASE
    assert release == {'schema': 1, 'releaseId': release_id, 'gvrSourceDate': '2026-11-19',
                       'gvrSourceSha256': SOURCE_SHA, 'torgiSnapshotDate': '2026-10-01'}
    assert all((site/name).read_bytes().count(release_id.encode()) == 1 for name in RELEASE_PAGES)
    assert any(('/' + ARCHIVE_PATH).encode() in chunk.read_bytes() for chunk in (site/'_next/static/chunks').glob('*.js'))
    verification = read(site/'data/verification.json')
    assert verification
    history_path = site/ARCHIVE_PATH
    assert sha(history_path) == KAZAN_SHA
    history = summarize_history(read(history_path))
    state = concordance(site)
    source, map_, tiles, unresolved, _, _, display, _ = state
    assert {key:map_['counts'][key] for key in COUNTS} == COUNTS
    assert source['sourceLedger']['recordsSha256'] == evidence['ledgerSha256']
    assert source['sourceLedger']['manifestSha256'] == evidence['ledgerManifestSha256']
    assert set(ids) <= tiles.keys() and not set(ids) & unresolved.keys()
    assert Counter(tiles[ident]['r'] for ident in ids) == REGIONS
    assert Counter(group['type'] for ident in ids for group in tiles[ident]['g']) == GROUPS
    city_geometry = digest([geometry_payload(tiles[ident]) for ident in ids])
    assert city_geometry == EXPECTED['cityGeometryPayloads'], 'Published cities differ from independently reviewed geometry'
    protected = protected_projections(state, site, ids)
    for key, checksum in protected.items():
        assert checksum == EXPECTED[key], f'Protected parts of the published site changed: {key}'
    return {
        'release': release, 'gvrCounts': COUNTS, 'cityRegions': REGIONS, 'cityGroups': GROUPS,
        'history': {'path':ARCHIVE_PATH, **receipt(history_path), **history},
        'protected': protected,
        'calculatedDisplay': {'records': len(display), **map_['files']['reassembledInference'],
                              'parts': map_['counts']['inference']['presentationPolygon']},
    }


def build_manifest(site, archive, source_receipt):
    ids, evidence = evidence_summary(read(source_receipt))
    return {'schema': 1, 'kind': 'gvr-city-source-with-kazan-history-full-site', 'predecessorReleaseId': OLD_RELEASE,
            'predecessorArchiveSha256': OLD_ARCHIVE_SHA, 'archive': receipt(archive), 'upgradedIds': ids,
            'sourceEvidence': {'receiptSha256': sha(source_receipt), **evidence}, **verify_site(site, ids, evidence)}


def verify_for_pages(site, archive, metadata_path):
    declared = read(metadata_path)
    evidence = declared['sourceEvidence']
    assert set(evidence) == {'receiptSha256', 'ledgerSha256', 'ledgerManifestSha256'}
    assert all(re.fullmatch(r'[a-f0-9]{64}', value) for value in evidence.values())
    ids = declared['upgradedIds']
    checked = {'schema': 1, 'kind': 'gvr-city-source-with-kazan-history-full-site', 'predecessorReleaseId': OLD_RELEASE,
               'predecessorArchiveSha256': OLD_ARCHIVE_SHA, 'archive': receipt(archive), 'upgradedIds': ids,
               'sourceEvidence': evidence, **verify_site(site, ids, evidence)}
    assert declared == checked, 'Full city Pages release receipt mismatch'
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command, identifier in (('reference', 'independent_review'), ('prepare', 'source_receipt'), ('verify', 'manifest')):
        sub = commands.add_parser(command)
        sub.add_argument('site', type=Path)
        sub.add_argument('archive', type=Path)
        sub.add_argument(identifier, type=Path)
    args = parser.parse_args()
    if args.command == 'reference':
        data = derive_expected(args.site, args.archive, args.independent_review)
    elif args.command == 'prepare':
        data = build_manifest(args.site, args.archive, args.source_receipt)
    else:
        data = verify_for_pages(args.site, args.archive, args.manifest)
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__=='__main__':
    main()
