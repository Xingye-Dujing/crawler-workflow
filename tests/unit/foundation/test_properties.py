"""Properties the shared helpers must hold for EVERY input, not just the ones a case names.

A guard written for one example ("this filename", "this column list") is a guard that fails on the
next example. These are the invariants a caller is entitled to: the helpers are idempotent, they do
not cut a character in half, and a blank stays blank. Seeded pseudo-random input keeps the suite
deterministic — a failing seed is printed so the case is reproducible.
"""

import random

import pandas as pd
import pytest
from core.refs import MAX_FILENAME_BYTES, sanitize_filename

from services.analysis.contracts import STEP_PARAMS, normalize_step_params
from services.analysis.matching import cell_text, value_key

pytestmark = pytest.mark.unit

#: A deterministic pool: ASCII, CJK, full-width punctuation, emoji, combining marks, separators.
ALPHABET = list('abcXYZ019-_ .<>:"/\\|?*') + list('中文测试数据') + ['，', '。', '！', '😀', 'é', 'e\u0301', '\u3000']


def _sample(rng, minimum=1, maximum=40):
    return ''.join(rng.choice(ALPHABET) for _ in range(rng.randint(minimum, maximum)))


class TestSanitizeFilename:
    def test_the_byte_cap_holds_and_the_name_stays_valid_utf8(self):
        rng = random.Random(20261124)
        for _ in range(200):
            source = _sample(rng, 1, 400)
            name = sanitize_filename(source)
            assert len(name.encode('utf-8')) <= MAX_FILENAME_BYTES, source[:40]
            assert name == name.encode('utf-8').decode('utf-8')
            assert not name.startswith('.') and not name.endswith(' '), repr(name)

    def test_sanitising_twice_changes_nothing(self):
        rng = random.Random(7)
        for _ in range(200):
            once = sanitize_filename(_sample(rng))
            assert sanitize_filename(once) == once

    def test_a_path_separator_never_survives(self):
        rng = random.Random(11)
        for _ in range(100):
            name = sanitize_filename(_sample(rng))
            assert '/' not in name and '\\' not in name


class TestTheAnalysisStepContract:
    def test_normalizing_twice_changes_nothing(self):
        samples = {
            'columns': ' 标题 ,  城市 ',
            'how': ' all ',
            'bins': '0, 5, 10',
            'phase_edges': '2022-01-01, 2022-02-01',
            'rename_from': ' 旧列 ',
        }
        for op, spec in STEP_PARAMS.items():
            params = {key: samples.get(key, ' 1 ') for key in (*spec.get('one', ()), *spec.get('some', ()))}
            once = normalize_step_params(op, params)
            assert normalize_step_params(op, once) == once, op

    def test_a_blank_select_becomes_its_declared_fallback(self):
        from services.analysis.contracts import NO_DEFAULT

        for op, spec in STEP_PARAMS.items():
            for key, (default, _allowed) in (spec.get('enums') or {}).items():
                normalized = normalize_step_params(op, {key: '   '})
                if default is NO_DEFAULT:
                    # No fallback: a blank stays blank so validate_step refuses it by name.
                    assert not str(normalized.get(key) or '').strip(), f'{op}.{key}'
                elif default is not None and not isinstance(default, bool):
                    assert normalized.get(key) == default, f'{op}.{key}'


class TestMatchKeys:
    def test_a_trim_key_is_idempotent(self):
        rng = random.Random(3)
        for _ in range(200):
            first = value_key(_sample(rng), 'trim')
            if not first:
                continue  # a blank states no identity: both sides are blank, by contract
            assert value_key(first, 'trim') == first

    def test_a_url_key_is_idempotent(self):
        for url in (
            'https://www.Weibo.com/u/42/?utm_source=x&id=7',
            'http://example.com/a/b/',
            'https://example.com',
        ):
            first = value_key(url, 'url')
            assert first and value_key(first, 'url') == first

    def test_a_blank_cell_states_no_identity(self):
        for blank in (None, '', '   ', '\u3000', pd.NA, float('nan')):
            assert cell_text(blank) in ('', '   ', '\u3000')  # raw text keeps what the cell held
            assert value_key(blank, 'trim') == ''
            assert value_key(blank, 'url') == ''
