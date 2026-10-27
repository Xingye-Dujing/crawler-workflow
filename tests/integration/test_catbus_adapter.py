"""The real adapter, when this machine has one.

No case here crawls a site or needs a login: `capabilities` and `preflight` are answered locally
(`preflight` reads CatBus' own account files and reports whether it is logged in — it sends nothing
anywhere). What they pin is the part a stub cannot: that the CLI on this box speaks the contract the
bridge parses, in the shape the panel filters itself against.

Like every other real dependency, an absent adapter SKIPS — and a skip can look like a passing tier,
so `CIXI_REQUIRE_CATBUS=1` turns absence into a failure when green is meant as evidence.
"""

import shutil

import pytest
from device_policy import REQUIRE_CATBUS_ENV, unavailable

from services import catbus_bridge as bridge

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope='module')
def adapter():
    """A machine that can answer its own capability question, or a skip with the real reason."""
    if shutil.which('node') is None and not bridge.machine_deps.find_node():
        # Node is the adapter's runtime, so "no Node" is the same fact as "no adapter" here:
        # skipping it under the flag would let the tier claim a manifest it never read.
        unavailable('no Node runtime on this machine', REQUIRE_CATBUS_ENV)
    info = bridge.probe(force=True)
    if not info.available:
        reason = bridge.t(info.reason_key, **info.reason_params)
        unavailable(f'no usable CatBus adapter on this machine: {reason}', REQUIRE_CATBUS_ENV)
    return info


class TestTheAdapterAnswers:
    def test_the_manifest_is_the_shape_the_bridge_parses(self, adapter):
        manifest = adapter.manifest
        assert manifest.get('backend') == 'catbus', manifest
        assert manifest.get('schema') == 1, 'a schema bump is a parsing change, not a surprise'
        cells = manifest['platforms']
        assert cells, 'the adapter offered no platform at all'
        for platform, entry in cells.items():
            assert entry.get('catbus_platform'), platform
            for mode, mode_entry in (entry.get('modes') or {}).items():
                assert mode_entry.get('status') in ('available', 'partial', 'planned', 'unavailable'), (
                    f'{platform}.{mode} invented a status'
                )
                # A cell that cannot be crawled owes the panel a reason, in the adapter's own words.
                if mode_entry['status'] not in bridge._RUNNABLE_STATES:
                    assert mode_entry.get('reason'), f'{platform}.{mode} is refused without saying why'

    def test_the_status_payload_and_the_manifest_agree(self, adapter):
        payload = bridge.status_payload()
        assert payload['available'] is True
        assert payload['panelKey'] == '', 'a machine that can run it has nothing to apologise for'
        for key, cell in payload['cells'].items():
            # Mode keys may contain dots (``user.followers``), so only the first one divides.
            platform, mode = key.split('.', 1)
            assert bridge.supports(platform, mode) is bool(cell['runnable']), key

    def test_a_supported_cell_names_its_columns_and_its_identity(self, adapter):
        seen = []
        for key, cell in bridge.status_payload()['cells'].items():
            if not cell['runnable']:
                continue
            platform, mode = key.split('.', 1)
            seen.append(key)
            assert bridge.columns_for(platform, mode), f'{key} promises rows with no columns'
            assert bridge.identity_for(platform, mode), f'{key} promises rows nobody can dedupe'
        assert seen, 'no cell of this adapter is runnable, which is a different answer than the tier expects'

    def test_every_read_function_the_real_manifest_offers_has_a_label_and_an_engine_cell(self, adapter):
        """The 3-D panel is generated from the REAL manifest, so its label catalogue must cover it.

        A mode added in CatBus is a new key here; a computed label would print the key itself, and a
        matrix that silently dropped the mode would paint another function as the one stored. Both
        halves are read off the adapter's own answer, not a fixture.
        """
        import crawl_capabilities as capabilities

        for platform, entry in adapter.manifest['platforms'].items():
            for mode in entry.get('modes') or {}:
                assert capabilities.CATBUS_MODE_LABELS.get(mode), f'{platform}.{mode} has no panel label'
        payload = capabilities.as_dict()
        by_platform = {p['platform']: p for p in payload['platforms']}
        for platform in adapter.manifest['platforms']:
            assert platform in by_platform, f'{platform} did not reach the panel payload'
            assert any(e['key'] == 'catbus' for e in by_platform[platform]['engines']), platform
        # The manifest names platforms Selenium has no class for; they must be listed, CatBus-only.
        assert 'kuaishou' in by_platform, 'a CatBus-only platform vanished from the panel'
        assert [e['key'] for e in by_platform['kuaishou']['engines']] == ['catbus']

    def test_preflight_answers_without_touching_a_cookie_file(self, adapter, tmp_path, monkeypatch):
        """CatBus' login is its own; the question must not read or write our cookie directory.

        The check is the directory: ``Config.COOKIE_DIR`` is pointed at an empty temp dir, so any
        answer that came from a Selenium cookie would arrive as 「没有 Cookie」 instead of the
        adapter's own 「未登录」.
        """
        from config import Config

        monkeypatch.setattr(Config, 'COOKIE_DIR', str(tmp_path))
        verdict = bridge.preflight(next(iter(adapter.manifest['platforms'])))
        assert set(verdict) >= {'available', 'logged_in', 'verdict', 'message', 'hint'}
        assert verdict['available'] is True
        assert verdict['verdict'] in ('valid', 'expired')
        if not verdict['logged_in']:
            assert 'catbus' in verdict['hint'], 'the remedy names the command, never a saved Cookie'
        assert list(tmp_path.iterdir()) == [], 'the login question wrote something into the cookie dir'
