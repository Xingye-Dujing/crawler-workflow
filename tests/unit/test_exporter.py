"""Tests for services/exporter.py — the "Save" node's writer.

Exports are the only artefact most users keep from a run, so the pinned
contracts are about the file that lands on disk:

- the format is decided by the explicit argument first, the extension second,
  and anything unknown is refused instead of silently written as CSV,
- a Chinese-speaking user's CSV must open in Excel (``utf-8-sig`` BOM) and a
  JSON export must contain no bare ``NaN`` token,
- the returned metadata (path/format/rows) matches the file that was written.
"""

import json
import os
import re
from pathlib import Path

import pandas as pd
import pytest

import services.exporter as exporter_module
from services.exporter import DataExporter as E
from services.exporter import UnsupportedFormatError

pytestmark = pytest.mark.unit


def _read(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def _json(path: str):
    return json.loads(_read(path))


@pytest.fixture
def df():
    return pd.DataFrame({'标题': ['三亚攻略', '海口美食'], '点赞': [12, 30]})


@pytest.mark.parametrize(
    'fmt, ext',
    [
        ('csv', '.csv'),
        ('json', '.json'),
        ('excel', '.xlsx'),
        ('txt', '.txt'),
        ('html', '.html'),
        ('markdown', '.md'),
    ],
)
def test_extension_matches_the_format(fmt, ext):
    assert E.EXTENSIONS[fmt] == ext


def test_the_format_list_has_no_duplicate_entries():
    """``xlsx`` used to sit in EXTENSIONS next to ``excel``, so the supported list
    named one format twice while the panel showed the other name. An alias is not
    a format."""
    assert len(set(E.SUPPORTED_FORMATS)) == len(E.SUPPORTED_FORMATS)
    assert 'xlsx' not in E.SUPPORTED_FORMATS and 'excel' in E.SUPPORTED_FORMATS
    assert [E.resolve(name) for name in ('xlsx', 'XLSX', 'xls', 'excel')] == ['excel'] * 4
    assert E.resolve('md') == 'markdown' and E.resolve('csv') == 'csv' and E.resolve('') == ''


def test_an_aliased_format_still_writes_the_real_file(tmp_path):
    """A saved workflow that says xlsx must keep working after the alias moved
    out of EXTENSIONS — resolving is not the same as rejecting."""
    result = E.save([{'a': 1}], str(tmp_path / 'aliased.xlsx'), fmt='xlsx')
    assert result['format'] == 'excel' and os.path.exists(result['path'])


class TestFormatSelection:
    @pytest.mark.parametrize(
        'filename, expected',
        [
            ('a.csv', 'csv'),
            ('a.JSON', 'json'),
            ('x.xlsx', 'excel'),
            ('y.xls', 'excel'),
            ('z.md', 'markdown'),
            ('w.html', 'html'),
            ('t.txt', 'txt'),
            ('no-extension', 'csv'),
            ('', 'csv'),
            ('.csv', 'csv'),
        ],
    )
    def test_format_is_inferred_from_the_name(self, filename, expected):
        assert E.infer_format(filename) == expected

    def test_supported_formats_match_the_panel_exactly(self):
        """The output node's format dropdown and this list are the same six
        names — a seventh entry the user can never pick (the old ``xlsx``
        duplicate) is a format that exists in one place and not the other.

        The source node legitimately offers a subset (csv/json), so every
        literal in the file is collected and one of them has to be the whole
        supported list; pinning "the first match" would test the wrong node.
        """
        import re
        from pathlib import Path

        assert E.SUPPORTED_FORMATS == ('csv', 'json', 'excel', 'txt', 'html', 'markdown')
        source = (Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'workflow.js').read_text(
            encoding='utf-8'
        )
        offered = [
            tuple(re.findall(r"'([a-z]+)'", group)) for group in re.findall(r"\[('(?:[^']|'[^'])*')\]\.map", source)
        ]
        assert E.SUPPORTED_FORMATS in offered, f'no panel list matches the supported formats: {offered}'
        # The same scan also catches unrelated dropdown literals (agg functions,
        # chart types), so only the entries that name a format are checked: no
        # format may be offered anywhere that the exporter would refuse.
        naming_formats = [names for names in offered if set(names) & set(E.SUPPORTED_FORMATS)]
        assert naming_formats, 'the scan found no format list at all'
        assert all(set(names) <= set(E.SUPPORTED_FORMATS) for names in naming_formats), naming_formats

    def test_an_explicit_format_beats_the_extension(self, df, tmp_path):
        target = str(tmp_path / 'out.csv')
        assert E.save(df, target, fmt='json')['format'] == 'json'
        assert _json(target)[0]['标题'] == '三亚攻略'

    @pytest.mark.parametrize('filepath', ['data.parq', 'weird.bin'])
    def test_an_unknown_format_is_refused(self, df, tmp_path, filepath):
        with pytest.raises(UnsupportedFormatError, match='Unsupported export format'):
            E.save(df, str(tmp_path / filepath))

    def test_an_unknown_explicit_format_is_refused(self, df, tmp_path):
        with pytest.raises(UnsupportedFormatError):
            E.save(df, str(tmp_path / 'a.csv'), fmt='parquet')


class TestNormalizeFilename:
    @pytest.mark.parametrize(
        'filename, fmt, expected',
        [
            ('report', 'csv', 'report.csv'),
            ('report.txt', 'csv', 'report.txt'),
            ('report.csv', 'csv', 'report.csv'),
            ('a.JSON', 'json', 'a.JSON'),
            ('report', 'excel', 'report.xlsx'),
            ('report', 'markdown', 'report.md'),
            ('', 'csv', 'export.csv'),
            ('   ', 'json', 'export.json'),
            ('.', 'csv', 'export.csv'),
            ('...', 'html', 'export.html'),
            ('deep/nested', 'csv', 'deep/nested.csv'),
        ],
    )
    def test_stems_get_the_right_extension(self, filename, fmt, expected):
        assert E.normalize_filename(filename, fmt) == expected

    def test_unknown_format_still_lands_on_csv(self):
        assert E.normalize_filename('data', 'parquet') == 'data.csv'


class TestStampFilename:
    """The shape of 「文件名追加本次运行时间」: every run keeps its own file.

    ``normalize_filename`` decides the suffix, this decides that a suffix the
    export panel can read survives the rename, and that the name it returns is
    a name nothing is sitting on yet.
    """

    def test_the_stamp_goes_before_the_extension(self, tmp_path):
        out = E.stamp_filename('report.csv', str(tmp_path))
        assert re.fullmatch(r'report-\d{8}-\d{6}\.csv', out), out

    @pytest.mark.parametrize('name', ['report.json', 'report.xlsx', 'notes.md', 'a.b.c.csv', '数据.csv'])
    def test_the_extension_survives_the_rename(self, name, tmp_path):
        assert E.stamp_filename(name, str(tmp_path)).endswith(os.path.splitext(name)[1])

    def test_a_name_taken_a_second_ago_becomes_the_next_number(self, tmp_path, monkeypatch):
        # The clock is frozen because otherwise the two calls can fall a second
        # apart, and the counter branch — the one a parallel canvas hits — never runs.
        monkeypatch.setattr(exporter_module.time, 'strftime', lambda _fmt: '20260924-081500')
        first = E.stamp_filename('report.csv', str(tmp_path))
        (tmp_path / first).write_text('kept', encoding='utf-8')
        second = E.stamp_filename('report.csv', str(tmp_path))
        assert second == 'report-20260924-081500-2.csv'
        (tmp_path / second).write_text('kept', encoding='utf-8')
        assert E.stamp_filename('report.csv', str(tmp_path)) == 'report-20260924-081500-3.csv'
        assert (tmp_path / first).read_text(encoding='utf-8') == 'kept', 'an earlier result is never rewritten'

    def test_the_name_it_returns_is_never_an_existing_file(self, tmp_path):
        for _ in range(3):
            name = E.stamp_filename('report.csv', str(tmp_path))
            assert not (tmp_path / name).exists()
            (tmp_path / name).write_text('x', encoding='utf-8')
        assert len(list(tmp_path.iterdir())) == 3


class TestSave:
    def test_metadata_describes_what_was_written(self, df, tmp_path):
        target = str(tmp_path / 'out.csv')
        result = E.save(df, target)
        assert result == {'path': target, 'format': 'csv', 'rows': 2}
        assert Path(target).exists()

    def test_csv_is_written_with_a_bom_for_excel(self, df, tmp_path):
        target = str(tmp_path / 'out.csv')
        E.save(df, target)
        raw = Path(target).read_bytes()
        assert raw.startswith(b'\xef\xbb\xbf')
        assert '三亚攻略' in raw.decode('utf-8-sig')

    def test_csv_round_trips_through_pandas(self, df, tmp_path):
        target = str(tmp_path / 'out.csv')
        E.save(df, target)
        assert pd.read_csv(target).equals(df)

    def test_json_turns_missing_numbers_into_null(self, tmp_path):
        frame = pd.DataFrame({'v': [1.0, None], 't': ['x', None]})
        target = str(tmp_path / 'out.json')
        E.save(frame, target)
        assert _json(target)[1] == {'v': None, 't': None}

    def test_json_keeps_chinese_readable(self, df, tmp_path):
        target = str(tmp_path / 'out.json')
        E.save(df, target)
        assert '\\u' not in _read(target)

    def test_json_supports_other_orients(self, df, tmp_path):
        target = str(tmp_path / 'out.json')
        E.save(df, target, orient='columns')
        assert _json(target)['标题']['0'] == '三亚攻略'

    def test_excel_round_trips(self, df, tmp_path):
        target = str(tmp_path / 'out.xlsx')
        assert E.save(df, target)['format'] == 'excel'
        assert pd.read_excel(target).equals(df)

    def test_excel_honours_a_sheet_name(self, df, tmp_path):
        target = str(tmp_path / 'named.xlsx')
        E.save(df, target, fmt='excel', sheet_name='数据')
        assert pd.read_excel(target, sheet_name='数据').equals(df)

    def test_txt_can_emit_one_column_per_line(self, df, tmp_path):
        target = str(tmp_path / 'out.txt')
        E.save(df, target, text_column='标题')
        assert _read(target).splitlines() == ['三亚攻略', '海口美食']

    def test_txt_without_a_text_column_writes_tsv_lines(self, df, tmp_path):
        target = str(tmp_path / 'out.txt')
        E.save(df, target)
        assert _read(target).splitlines()[0] == '三亚攻略\t12'

    def test_txt_ignores_a_column_that_is_not_in_the_frame(self, df, tmp_path):
        target = str(tmp_path / 'fallback.txt')
        E.save(df, target, text_column='nope')
        assert '\t' in _read(target)

    def test_html_escapes_the_values(self, tmp_path):
        target = str(tmp_path / 'out.html')
        E.save(pd.DataFrame({'v': ['<b>bold</b>']}), target)
        body = _read(target)
        assert '<table' in body and '&lt;b&gt;' in body

    def test_markdown_produces_a_table(self, df, tmp_path):
        target = str(tmp_path / 'out.md')
        E.save(df, target)
        lines = _read(target).splitlines()
        assert lines[0].startswith('|') and lines[0].endswith('|')
        assert set(lines[1]) <= set('|-: ') and lines[1].startswith('|')
        assert '三亚攻略' in lines[2]

    def test_accepts_a_list_of_records(self, tmp_path):
        target = str(tmp_path / 'records.csv')
        result = E.save([{'a': 1}, {'a': 2}], target)
        assert result['rows'] == 2
        assert pd.read_csv(target)['a'].tolist() == [1, 2]

    def test_accepts_no_data_at_all(self, tmp_path):
        target = str(tmp_path / 'empty.csv')
        assert E.save([], target)['rows'] == 0
        # Nothing to write: only the BOM and a line break survive.
        assert Path(target).read_text(encoding='utf-8-sig').strip() == ''

    def test_creates_the_destination_directory(self, df, tmp_path):
        nested = tmp_path / 'a' / 'b' / 'out.csv'
        E.save(df, str(nested))
        assert nested.exists()

    def test_an_overwrite_is_a_replace(self, df, tmp_path):
        target = str(tmp_path / 'twice.csv')
        E.save(df, target)
        E.save(df.head(1), target)
        assert E.save(df.head(1), target)['rows'] == 1
