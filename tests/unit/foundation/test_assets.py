"""The asset record round-trips and refuses anything a store cannot trust.

P2 will persist these rows; a shape that accepts a missing owner or a list where parents belong
becomes a corrupt lineage entry that no later migration can repair. So the refusal cases are the
contract, not an afterthought: each names the field, and a record serialised now must read back
byte-for-byte through JSON.
"""

import json

import pytest
from core.asset import ASSET_KINDS, SCHEMA_VERSION, AssetError, DataAsset

pytestmark = pytest.mark.unit

HEX = 'a' * 64


def _asset(**overrides) -> DataAsset:
    values = {
        'id': 'asset:run-1:node-2',
        'kind': 'table',
        'owner': 'default',
        'origin': 'run:run-1:node-2',
        'sha256': HEX,
        'size': 1200,
        'uri': 'run:run-1:node:node-2',
        'parents': ('asset:upload:9',),
        'meta': {'rows': 120},
        'created_at': '2026-11-22T10:00:00+08:00',
    }
    values.update(overrides)
    return DataAsset(**values)


class TestTheRecord:
    def test_a_well_formed_asset_has_no_problem(self):
        assert _asset().problems() == []

    def test_every_declared_kind_is_accepted(self):
        for kind in ASSET_KINDS:
            assert _asset(kind=kind).problems() == [], kind

    def test_json_round_trip_preserves_the_record(self):
        original = _asset()
        restored = DataAsset.from_dict(json.loads(json.dumps(original.to_dict())))
        assert restored == original

    def test_writing_does_not_share_the_meta_object(self):
        original = _asset(meta={'rows': 120})
        written = original.to_dict()
        written['meta']['rows'] = 1
        assert original.meta == {'rows': 120}

    def test_two_default_meta_objects_are_not_shared(self):
        first = _asset()
        second = _asset()
        assert first.meta is not second.meta

    def test_the_schema_is_the_current_one(self):
        assert _asset().schema == SCHEMA_VERSION
        assert _asset().to_dict()['schema'] == SCHEMA_VERSION


class TestTheRefusals:
    def _problems(self, **overrides):
        return _asset(**overrides).problems()

    def test_an_unknown_kind_is_named(self):
        assert any('kind' in line for line in self._problems(kind='moonbase'))

    def test_a_missing_owner_or_origin_or_uri_is_named(self):
        for field in ('owner', 'origin', 'uri'):
            assert any(line.startswith(f'{field}:') for line in self._problems(**{field: ' '})), field

    def test_a_bad_hash_and_size_are_named(self):
        assert any('sha256' in line for line in self._problems(sha256='abc'))
        assert any('size' in line for line in self._problems(size=-1))
        assert any('size' in line for line in self._problems(size=True))

    def test_an_asset_cannot_be_its_own_parent(self):
        asset = _asset(id='asset:1', parents=('asset:1',))
        assert any('own parent' in line for line in asset.problems())

    def test_a_duplicate_parent_is_named(self):
        asset = _asset(parents=('asset:a', 'asset:a'))
        assert any('duplicate' in line for line in asset.problems())

    def test_a_future_schema_is_refused(self):
        asset = _asset(schema=SCHEMA_VERSION + 1)
        assert any('schema' in line for line in asset.problems())

    def test_a_non_json_meta_is_named(self):
        assert any('meta' in line for line in self._problems(meta={'x': {1, 2}}))

    def test_a_bad_timestamp_is_named(self):
        assert any('created_at' in line for line in self._problems(created_at='yesterday'))


class TestFromDictRefusals:
    def _payload(self):
        return _asset().to_dict()

    def test_an_unknown_field_is_refused_by_name(self):
        payload = self._payload() | {'secret': 'x'}
        with pytest.raises(AssetError, match='unknown field.*secret'):
            DataAsset.from_dict(payload)

    def test_a_missing_required_field_is_refused_by_name(self):
        payload = self._payload()
        payload.pop('owner')
        with pytest.raises(AssetError, match='missing field.*owner'):
            DataAsset.from_dict(payload)

    def test_a_non_object_is_refused(self):
        with pytest.raises(AssetError, match='not an object'):
            DataAsset.from_dict(['x'])

    def test_a_semantically_invalid_record_is_refused(self):
        payload = self._payload()
        payload['meta'] = {'x': {1, 2}}
        with pytest.raises(AssetError, match='meta'):
            DataAsset.from_dict(payload)
