"""A migration switch must be owned, explained, and gone by its date.

The switch mechanism is small; the failure it prevents is not. A flag added "for now" outlives the
migration, both paths stay live, and the next reader cannot tell which one ships. The gate calls
``flags.problems()`` with today's date; these cases prove it can fail on an expired/malformed switch
even while the real registry is empty.
"""

from datetime import date

import pytest
from runtime import flags

pytestmark = pytest.mark.unit

NOW = date(2026, 11, 22)


def _flag(**overrides):
    values = {
        'name': 'kernel_nodes',
        'owner': '@architecture',
        'remove_by': '2027-06-01',
        'description': 'Run the node catalogue from manifests instead of nodes/catalog.py.',
        'default': False,
    }
    values.update(overrides)
    return flags.Flag(**values)


class TestTheRealRegistry:
    def test_there_is_no_switch_left_behind(self):
        assert flags.problems(today=NOW) == []
        assert flags.expired(today=NOW) == []

    def test_an_undeclared_switch_is_refused_by_name(self):
        with pytest.raises(flags.FlagError, match='unknown migration flag'):
            flags.flag_for('kernel_nodes')
        with pytest.raises(flags.FlagError, match='unknown migration flag'):
            flags.active('kernel_nodes')


class TestTheGateCanFail:
    def test_an_expired_switch_is_named_with_its_owner_and_date(self):
        expired = _flag(remove_by='2026-11-01')
        found = flags.problems(declared=(expired,), today=NOW)
        assert any('expired on 2026-11-01' in line and '@architecture' in line for line in found), found

    def test_the_removal_date_itself_is_still_allowed(self):
        live = _flag(remove_by='2026-11-22')
        assert flags.problems(declared=(live,), today=NOW) == []
        assert flags.problems(declared=(live,), today=date(2026, 11, 23)) != []

    def test_a_malformed_date_is_named(self):
        found = flags.problems(declared=(_flag(remove_by='next year'),), today=NOW)
        assert any('not YYYY-MM-DD' in line for line in found), found

    def test_a_switch_without_owner_or_reason_is_refused(self):
        found = flags.problems(declared=(_flag(owner=''),), today=NOW)
        assert any('no owner' in line for line in found), found
        found = flags.problems(declared=(_flag(description=''),), today=NOW)
        assert any('no description' in line for line in found), found

    def test_a_duplicate_name_is_refused(self):
        found = flags.problems(declared=(_flag(), _flag()), today=NOW)
        assert any('declared twice' in line for line in found), found

    def test_a_non_boolean_default_is_refused(self):
        found = flags.problems(declared=(_flag(default='false'),), today=NOW)
        assert any('not a boolean' in line for line in found), found


class TestTheEnvironmentIsTriState:
    def _install(self, monkeypatch, default=False):
        flag = _flag(default=default)
        monkeypatch.setitem(flags.FLAGS, flag.name, flag)
        return flag

    def test_blank_means_the_declared_default_not_false(self, monkeypatch):
        monkeypatch.delenv('CIXI_FLAG_KERNEL_NODES', raising=False)
        self._install(monkeypatch, default=True)
        assert flags.active('kernel_nodes') is True

    def test_true_and_false_spellings_are_read(self, monkeypatch):
        self._install(monkeypatch)
        for value in ('1', 'true', 'YES', 'on'):
            monkeypatch.setenv('CIXI_FLAG_KERNEL_NODES', value)
            assert flags.active('kernel_nodes') is True, value
        for value in ('0', 'false', 'NO', 'off'):
            monkeypatch.setenv('CIXI_FLAG_KERNEL_NODES', value)
            assert flags.active('kernel_nodes') is False, value

    def test_a_typo_is_refused_not_coerced(self, monkeypatch):
        self._install(monkeypatch)
        monkeypatch.setenv('CIXI_FLAG_KERNEL_NODES', 'treu')
        with pytest.raises(flags.FlagError, match='not a boolean'):
            flags.active('kernel_nodes')

    def test_the_environment_key_is_derived_from_the_name(self):
        assert _flag(name='kernel.nodes-2').env_key() == 'CIXI_FLAG_KERNEL_NODES_2'

    def test_require_live_raises_the_same_list(self, monkeypatch):
        monkeypatch.setitem(flags.FLAGS, 'old', _flag(name='old', remove_by='2020-01-01'))
        with pytest.raises(flags.FlagError, match='expired'):
            flags.require_live(today=NOW)
