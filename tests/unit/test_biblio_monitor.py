"""Cross-run monitoring: file one network per run and diff it against the capture before it.

The comparison itself (``compare_snapshots``) is covered in the project/snapshot tests; what lives
here is the monitor's own behaviour — the parts a researcher feels: which capture becomes the
baseline, what the console says, what the CSV holds, and the cases where it refuses instead of
filing a misleading history.
"""

import csv
from pathlib import Path

import pytest

from i18n import t
from services.biblio_monitor import WATCH_COLUMNS, watch
from services.biblio_store import BiblioStore

pytestmark = pytest.mark.unit


def _nodes(*names, burst=(), cluster='0', label='数字治理'):
    rows = []
    for index, name in enumerate(names):
        row = {
            '节点': name,
            '类型': 'keyword',
            '频次': 10 - index,
            '首年': 2018,
            '末年': 2020,
            '连接': [{'target': names[(index + 1) % len(names)], 'value': 0.5, 'count': 3}],
            '聚类': cluster,
            '聚类标签': label,
        }
        if name in burst:
            row['突现强度'] = 2.5
        rows.append(row)
    return rows


class _Ctx:
    """The minimum the monitor reads from the run: an export directory of its own."""


def _run(rows, params, biblio, export_dir, *, stamp='2026-10-24 09:00:00', node_id='node-2', run_id='run-a'):
    return watch(
        rows,
        params,
        node_id=node_id,
        run_id=run_id,
        workflow_name='监测演示',
        entity_type='keyword',
        shape=str(params.get('output_shape') or 'nodes'),
        biblio=biblio,
        export_dir=str(export_dir),
        stamp=stamp,
    )


@pytest.fixture
def biblio(tmp_path) -> BiblioStore:
    return BiblioStore(db_path=str(tmp_path / 'biblio.db'))


@pytest.fixture
def export_dir(tmp_path) -> Path:
    target = tmp_path / 'exports'
    target.mkdir()
    return target


class TestTheFirstCapture:
    def test_an_empty_project_name_is_no_watch_at_all(self, biblio, export_dir):
        """Every canvas written before this parameter existed must behave byte-for-byte as before."""
        assert _run(_nodes('甲'), {}, biblio, export_dir) is None
        assert biblio.list_projects() == []

    def test_a_missing_project_is_created_and_says_so(self, biblio, export_dir):
        result = _run(_nodes('甲'), {'watch_project': '数字治理监测'}, biblio, export_dir)
        assert [p['name'] for p in biblio.list_projects()] == ['数字治理监测']
        assert any(t('biblio.watch_project_created', name='数字治理监测') in line for line in result['notes'])

    def test_the_first_run_has_nothing_to_compare_and_says_that_instead_of_nothing(self, biblio, export_dir):
        result = _run(_nodes('甲', '乙'), {'watch_project': 'P'}, biblio, export_dir)
        assert result['baseline'] is None
        assert result['diff'] is None
        assert any('无更早的快照可比' in line or 'nothing older' in line for line in result['notes'])
        rows = _read(result['file'])
        assert rows[0]['类别'] == t('biblio.watch.first')
        # 甲→乙 and 乙→甲 are one undirected pair, so two nodes and one link.
        assert rows[0]['后值'] == '2/1'

    def test_the_capture_is_named_after_the_run_moment_not_its_id(self, biblio, export_dir):
        """A panel list of run ids is not a timeline; a list of timestamps is."""
        result = _run(_nodes('甲'), {'watch_project': 'P'}, biblio, export_dir, stamp='2026-10-24 09:00:00')
        assert result['snapshot']['label'] == '2026-10-24 09:00:00'
        named = _run(_nodes('甲'), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        assert named['snapshot']['label'] == '基线'


class TestTheBaseline:
    def test_the_previous_capture_is_the_default_baseline(self, biblio, export_dir):
        first = _run(_nodes('甲', '乙'), {'watch_project': 'P'}, biblio, export_dir, run_id='run-1')
        second = _run(_nodes('甲', '乙', '丙'), {'watch_project': 'P'}, biblio, export_dir, run_id='run-2')
        assert second['baseline']['snapshot_id'] == first['snapshot']['snapshot_id']
        assert [name for name in second['diff']['nodes']['added']['items']] == ['丙']

    def test_a_named_baseline_jumps_back_over_newer_captures(self, biblio, export_dir):
        """Without the box the comparison means "since last time"; with it the researcher chooses
        which time — so the newest capture must not be dragged in as the reference.

        All four captures are filed inside the same second, and the labels are deliberately in an
        order that is NOT their codepoint order: the store's "newest first" used to break a
        ``created_at`` tie on the label, which made the default reference an arbitrary one.
        """
        _run(_nodes('甲', '乙'), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir, run_id='run-1')
        _run(
            _nodes('甲', '乙', '丙'),
            {'watch_project': 'P', 'watch_label': '第二次'},
            biblio,
            export_dir,
            run_id='run-2',
        )
        third = _run(
            _nodes('甲', '乙'),
            {'watch_project': 'P', 'watch_label': '第三次', 'watch_baseline': '基线'},
            biblio,
            export_dir,
            run_id='run-3',
        )
        assert third['baseline']['label'] == '基线'
        # Against 基线 nothing moved; against the default reference (第二次) 丙 would read as gone.
        assert third['diff']['nodes']['added']['total'] == 0
        assert third['diff']['nodes']['removed']['total'] == 0
        default = _run(
            _nodes('甲', '乙'), {'watch_project': 'P', 'watch_label': '第四次'}, biblio, export_dir, run_id='run-4'
        )
        assert default['baseline']['label'] == '第三次', 'the default reference is the capture before this one'

    def test_a_baseline_that_does_not_exist_is_refused_and_lists_what_does(self, biblio, export_dir):
        _run(_nodes('甲'), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        with pytest.raises(ValueError) as err:
            _run(_nodes('甲'), {'watch_project': 'P', 'watch_baseline': '上个月的'}, biblio, export_dir)
        assert '上个月的' in str(err.value)
        assert '基线' in str(err.value), 'the refusal names what it could have used'


class TestWhatTheConsoleSays:
    def test_only_what_moved_is_spelled_out_and_the_zeros_fold_away(self, biblio, export_dir):
        _run(_nodes('甲', '乙', burst=('甲',)), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        result = _run(
            _nodes('甲', '乙', '丙', burst=('甲',)),
            {'watch_project': 'P', 'watch_label': '本周', 'watch_baseline': '基线'},
            biblio,
            export_dir,
        )
        line = next(entry for entry in result['notes'] if '基线' in entry and '本周' in entry)
        assert f'{t("biblio.watch.node_added")} 1' in line
        assert t('biblio.watch.burst_removed') not in line, 'a category that did not move is not printed'
        assert '无变化' not in line

    def test_an_identical_graph_says_so_and_points_at_the_upstream(self, biblio, export_dir):
        rows = _nodes('甲', '乙')
        _run(rows, {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        result = _run(rows, {'watch_project': 'P', 'watch_label': '本周', 'watch_baseline': '基线'}, biblio, export_dir)
        assert any(t('biblio.watch.nothing') in line for line in result['notes'])
        assert any('上游' in line or 'upstream' in line for line in result['notes']), (
            'a monitor that reports "no change" without saying why reads as a broken clock'
        )

    def test_a_parameter_edit_is_reported_as_a_parameter_edit_not_as_the_field_moving(self, biblio, export_dir):
        rows = _nodes('甲', '乙')
        _run(rows, {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        result = _run(
            rows,
            {'watch_project': 'P', 'watch_label': '本周', 'watch_baseline': '基线', 'top_n': 99},
            biblio,
            export_dir,
        )
        assert any(t('biblio.watch_params_differ', n=1, names='top_n') in line for line in result['notes'])
        assert not any(t('biblio.watch_unchanged', nodes=0, edges=0)[:10] in line for line in result['notes'])


class TestRefusals:
    def test_a_shape_whose_rows_are_not_entities_is_refused_by_name(self, biblio, export_dir):
        with pytest.raises(ValueError) as err:
            _run(_nodes('甲'), {'watch_project': 'P', 'output_shape': 'variation'}, biblio, export_dir)
        assert 'variation' in str(err.value)

    def test_an_empty_graph_is_refused_because_it_would_erase_the_history(self, biblio, export_dir):
        """A zero-row capture would make the NEXT run report every entity as gone — the one failure
        mode a monitor must not produce."""
        with pytest.raises(ValueError):
            _run([], {'watch_project': 'P'}, biblio, export_dir)

    def test_a_baseline_without_a_project_is_refused_before_the_run(self):
        from services.biblio_schema import collect_errors

        errors = collect_errors({'watch_baseline': '基线'}, 'node-2')
        assert any('监测' in str(error) or 'project' in str(error) for error in errors), errors


class TestTheArtifact:
    def test_the_csv_carries_one_row_per_change_with_its_two_values(self, biblio, export_dir):
        _run(_nodes('甲', '乙', cluster='0'), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        result = _run(
            _nodes('甲', '乙', cluster='1', label='乡村振兴'),
            {'watch_project': 'P', 'watch_label': '本周', 'watch_baseline': '基线'},
            biblio,
            export_dir,
        )
        rows = _read(result['file'])
        assert list(rows[0]) == list(WATCH_COLUMNS)
        kinds = {row['类别'] for row in rows}
        assert t('biblio.watch.cluster_added') in kinds
        assert t('biblio.watch.cluster_removed') in kinds
        assert t('biblio.watch.node_changed') in kinds
        moved = next(
            row for row in rows if row['类别'] == t('biblio.watch.node_changed') and row['名称'].endswith('聚类')
        )
        assert (moved['前值'], moved['后值']) == ('0', '1')

    def test_the_totals_are_reported_even_though_the_names_are_capped(self, biblio, export_dir):
        """The diff caps what it NAMES; the artifact has to say how many there really were, or a
        capped list reads as the whole change set."""
        _run(_nodes(*[f'甲{i}' for i in range(70)]), {'watch_project': 'P', 'watch_label': '基线'}, biblio, export_dir)
        result = _run(_nodes('甲0'), {'watch_project': 'P', 'watch_label': '本周'}, biblio, export_dir)
        assert result['diff']['nodes']['removed']['total'] == 69
        assert len(result['diff']['nodes']['removed']['items']) == 60


def _read(path: str) -> list[dict]:
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))
