"""The export guide's own contract: the panel may not know more or less than the parser.

The guide is the only place the app tells a user what a vendor's export contains, so it is
tested the way the cookie guide is — enumerated from the registry, not from a list someone
remembers to update — and every assertion is about a claim the panel makes to a user.
"""

import re

import pytest

from services import biblio_formats, biblio_sources
from services.biblio_import import CNKI, CSSCI

pytestmark = pytest.mark.unit

#: The sources the panel answers for: the registry's formats plus the two Chinese paths that
#: live in ``biblio_import``. Read from the registry so a new format cannot ship unread.
EXPECTED = [CSSCI, CNKI] + list(biblio_formats.format_ids())


class TestTheCatalogCoversTheReaders:
    def test_every_readable_source_is_described(self):
        assert [entry['id'] for entry in biblio_sources.all_sources()] == EXPECTED

    def test_no_source_is_invented_for_a_reader_that_does_not_exist(self):
        readers = {CNKI, CSSCI} | set(biblio_formats.format_ids())
        assert set(biblio_sources.SITES) <= readers, (
            f'guide names a source nobody can import: {set(biblio_sources.SITES) - readers}'
        )

    def test_extensions_and_capabilities_come_from_the_registry(self):
        """Restating them here would let the panel promise a column the parser never fills."""
        for entry in biblio_sources.all_sources():
            spec = biblio_formats.FORMAT_BY_ID.get(entry['id'])
            if spec is None:
                continue
            assert entry['extensions'] == list(spec.extensions)
            assert entry['capabilities'] == {name: name in spec.capabilities for name in biblio_formats.CAPABILITIES}

    def test_the_upload_dialog_is_asked_for_exactly_what_the_readers_accept(self):
        """``accepted_extensions`` had no caller for a long time; the file picker is that caller.

        Every extension the guide lists has to be one the upload route will try to parse, or a
        user is offered a file type that comes back as an ordinary table.
        """
        offered = {extension for entry in biblio_sources.all_sources() for extension in entry['extensions']}
        accepted = set(biblio_formats.accepted_extensions())
        assert accepted <= offered, f'the registry accepts what no entry advertises: {accepted - offered}'


class TestEveryEntrySaysSomethingTrue:
    @pytest.mark.parametrize('fmt', EXPECTED)
    def test_a_source_has_a_site_a_reason_and_at_least_one_step(self, fmt):
        entry = biblio_sources.source_for(fmt)
        assert re.match(r'^https://[a-z0-9.-]+\.[a-z]{2,}/$', str(entry['site'])), (
            f'{fmt}: the panel hands the user a link; it has to be a full https URL'
        )
        purpose = str(entry['purpose'])
        assert purpose and not purpose.startswith('source.'), f'{fmt}: purpose came back untranslated'
        assert len(entry['steps']) >= 1, f'{fmt}: a guide with no steps is a label'
        assert all(str(line).strip() for line in entry['steps'])
        assert entry['missing'], f'{fmt}: every real export lacks something; saying so is the point'

    @pytest.mark.parametrize('fmt', EXPECTED)
    def test_the_steps_are_numbered_in_the_order_the_user_follows_them(self, fmt):
        steps = [str(line) for line in biblio_sources.source_for(fmt)['steps']]
        assert [line.split('.')[0] for line in steps] == [str(number) for number in range(1, len(steps) + 1)], steps

    def test_lens_is_not_a_source_because_no_lens_file_was_ever_read(self):
        """The only Lens export we were given is the patent collection, which is refused."""
        assert 'Lens' not in EXPECTED
        assert 'Lens' not in {spec.id for spec in biblio_formats.FORMAT_SPECS}

    def test_the_tag_folding_matches_what_cssci_actually_writes(self):
        assert biblio_sources.folded_tag('关 键 词') == '关键词'
        assert biblio_sources.folded_tag('期\u3000\u3000刊') == '期刊'
