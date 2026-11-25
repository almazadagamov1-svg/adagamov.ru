"""Verify a reviewed full-source correction against the exact first release."""

from collections import Counter, defaultdict
from hashlib import sha256
import json

PREVIOUS_RELEASE = 'a56bacc7b6d35c1f'
PREVIOUS_MANIFEST_SHA = '2d6f3a5d507ba77d1dcf141c358d1698fe8b2761cd676754d63fa0237ae7f3dd'
PREVIOUS_ARCHIVE_SHA = '3eb2d78560d6004d0a8aa748bd11e4d81a3c076526012a53e4156f6f2b85b86d'
PREVIOUS_INDEX_SHA = 'be1ff0aaecace1e0442c0c5f427bb32457b08c2be4b2f27cdd1e69611486b628'
PREVIOUS_MANIFEST = 'predecessor-manifest.json'
PREVIOUS_ARCHIVE = 'predecessor-overlay.tar.gz'
CERTIFICATE = 'revision.json'


def digest(data):
    return sha256(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def find_source_records(site, ids, expected_source_sha):
    source = site / 'data/gvr'
    manifest = json.loads((source / 'manifest.json').read_bytes())
    assert manifest['sourceSha256'] == expected_source_sha
    found = {}
    for tile, meta in manifest['tiles'].items():
        body = (source / 'tiles' / (tile + '.json')).read_bytes()
        for row in json.loads(body):
            ident = row['id']
            if ident not in ids:
                continue
            assert len(body) == meta['bytes'] and sha256(body).hexdigest() == meta['sha256'], tile
            assert ident not in found or found[ident] == row, ident
            found[ident] = row
    assert found.keys() == ids, 'A declared revision record is absent from the source'
    return found


def verify_full_coverage(entries, record):
    groups = record['g']
    provenance = record.get('v', {})
    assert not provenance.get('partialSource')
    assert all(group['type'] in {'line', 'multi_point'} and not group.get('partialSource') for group in groups)
    coordinates = [point for group in groups for point in group['coordinates']]
    assert coordinates
    expected_groups = list(range(len(groups)))
    parts = [entry for entry in entries if entry[5] == 'R']
    assert parts, 'A full-source revision must contain numbered parts'
    assert len({entry[0] for entry in parts}) == 1, 'Revision has several display owners'
    visited = Counter()
    for entry in entries:
        if entry[5] != 'R':
            assert entry == [entry[0], 'N', [], [], 0, 'N'], 'Unexpected display in a fully accounted revision record'
            continue
        assert len(entry) == 9 and entry[1] == 'P' and entry[3:5] == [[], 0] and entry[6] == []
        assert entry[7] == expected_groups, 'The display owner does not cover every source group'
        assert isinstance(entry[8], list) and 1 <= len(entry[8]) <= 3, 'Numbered source spans are empty'
        positions = []
        for start, end in entry[8]:
            assert type(start) is int and type(end) is int and 0 <= start < end <= len(coordinates)
            positions.extend(range(start, end))
        visited.update(positions)
        ring = []
        for i in positions:
            if not ring or coordinates[i] != coordinates[ring[-1]]:
                ring.append(i)
        if len(ring) > 1 and coordinates[ring[0]] == coordinates[ring[-1]]:
            ring.pop()
        assert entry[2] == ring and len({tuple(coordinates[i]) for i in ring}) >= 3, 'Polygon does not follow its source spans'
    assert visited == Counter(range(len(coordinates))), 'The numbered parts reuse or omit source positions'
    return len(parts)


def group_entries(entries):
    groups = defaultdict(list)
    for entry in entries:
        groups[entry[0]].append(entry)
    return dict(groups)


def ordinary_additions(previous, candidate, record_ids):
    additions = {}
    for ident in record_ids:
        old_entries = group_entries(previous[ident])
        new_entries = group_entries(candidate[ident])
        assert old_entries.keys() == new_entries.keys(), 'An ordinary addition changed eligible groups'
        for group in old_entries:
            before, after = old_entries[group], new_entries[group]
            if before == after:
                continue
            assert all(entry[1] in {'N', 'O'} for entry in before), 'An ordinary addition changed a previous polygon'
            assert all(entry[1] == 'P' and entry[5] in {'M', 'U'} for entry in after), 'Unexpected method in an ordinary addition'
            additions[(ident, group)] = (before, after)
    return additions


def verify_ordinary_addition(record, group_index, entries):
    assert record.get('v', {}).get('sourceCrs') == 'WGS-84'
    assert not record.get('v', {}).get('partialSource')
    group = record['g'][group_index]
    assert group['type'] in {'line', 'multi_point'} and not group.get('partialSource')
    coordinates = group['coordinates']
    for entry in entries:
        assert len(entry) in (6, 7) and entry[3] == [] and entry[4] == 0
        for ring in [entry[2], *(entry[6] if len(entry) == 7 else [])]:
            assert all(type(index) is int and 0 <= index < len(coordinates) for index in ring)
            assert len({tuple(coordinates[index]) for index in ring}) >= 3


def compare_records(original, previous, candidate, ids, site, source_sha):
    assert isinstance(ids, list) and ids and all(isinstance(ident, str) and ident for ident in ids)
    ids_set = set(ids)
    assert len(ids) == len(ids_set), 'Duplicate reviewed revision record'
    assert list(previous) == list(candidate), 'Display record order or inventory changed'
    changed = {ident for ident in previous if previous[ident] != candidate[ident]}
    assert ids_set <= changed, 'Listed revision records must have changed'
    additions = ordinary_additions(previous, candidate, changed - ids_set)
    source_records = find_source_records(site, changed, source_sha)
    revisions = []
    for ident in sorted(ids):
        record = source_records[ident]
        previous_entries = previous[ident]
        new_entries = candidate[ident]
        assert list(group_entries(new_entries)) == list(group_entries(previous_entries)), 'Eligible display groups changed'
        parts = verify_full_coverage(new_entries, record)
        revisions.append({
            'recordId': ident,
            'originalEntriesSha256': digest(original.get(ident, [])),
            'predecessorEntriesSha256': digest(previous_entries),
            'candidateEntriesSha256': digest(new_entries),
            'sourceRecordSha256': digest(record),
            'sourcePositions': sum(len(group['coordinates']) for group in record['g']),
            'parts': parts,
        })
    added = []
    for (ident, group_index), (before, after) in sorted(additions.items()):
        record = source_records[ident]
        verify_ordinary_addition(record, group_index, after)
        added.append({
            'recordId': ident,
            'group': group_index,
            'predecessorEntriesSha256': digest(before),
            'candidateEntriesSha256': digest(after),
            'sourceRecordSha256': digest(record),
            'parts': len(after),
        })
    for ident in changed - ids_set:
        preserved_before = [entry for entry in previous[ident] if (ident, entry[0]) not in additions]
        preserved_after = [entry for entry in candidate[ident] if (ident, entry[0]) not in additions]
        assert preserved_before == preserved_after, 'Previously displayed entries moved within a record'
    return revisions, added


def certificate(original_index, previous_index, candidate_index, ids, site, read_index, source_sha):
    assert sha256(previous_index).hexdigest() == PREVIOUS_INDEX_SHA
    _, original = read_index(original_index)
    _, previous = read_index(previous_index)
    _, candidate = read_index(candidate_index)
    revisions, added = compare_records(original, previous, candidate, ids, site, source_sha)
    if added:
        assert 'wgsSectionsSha256' in json.loads(candidate_index), 'WGS section helper is not pinned'
    return {
        'schema': 1,
        'mode': 'full-numbered-source-coverage',
        'sourceSha256': source_sha,
        'predecessorReleaseId': PREVIOUS_RELEASE,
        'predecessorManifestSha256': PREVIOUS_MANIFEST_SHA,
        'predecessorIndexSha256': PREVIOUS_INDEX_SHA,
        'candidateIndexSha256': sha256(candidate_index).hexdigest(),
        'revisionRecords': revisions,
        'addedWgsGroups': added,
    }
