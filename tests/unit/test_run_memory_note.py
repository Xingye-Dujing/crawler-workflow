"""What the run console says about the rows it is holding in memory.

``execution_state['results']`` keeps EVERY node's rows for the whole run — a preview reads
it and so does every child node — so the row caps elsewhere bound something else entirely:
``RUN_MAX_ROWS_PER_NODE`` is a DISK cap (it stops a runaway crawl filling ``runs.db``) and
``DATASET_MAX_ROWS`` caps one uploaded file. Neither is about what is resident, and an
out-of-memory kill three nodes later carries no node name at all.

So the run says it out loud, above a threshold, and these tests pin the two halves of that:
it speaks when the number matters, and it stays quiet when it does not — a notice on every
run would be noise the user learns to skip.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    """The application module, imported inside the test and never at module scope.

    ``tests/unit/test_test_tiers.py`` refuses a module-level ``import app``: collection
    imports every file before any fixture runs, so the app would be built while
    ``Config.DATA_DIR`` still pointed at the repository.
    """
    import app

    return app


@pytest.fixture
def spoken(exec_, monkeypatch):
    """Capture the console lines instead of writing them.

    ``add_log`` is the one door into the console buffer, so replacing it keeps this file
    from having to reason about ``clean_globals``' leak check — nothing is left running and
    no buffer is touched.
    """
    lines = []
    monkeypatch.setattr(exec_, 'add_log', lambda message, **kwargs: lines.append(message))
    return lines


class TestHeavyResultNotice:
    def test_a_small_result_says_nothing(self, exec_, spoken):
        exec_._note_heavy_result([{'a': 1}] * 10, '清洗 #n1')
        assert spoken == []

    def test_one_row_below_the_threshold_still_says_nothing(self, exec_, spoken):
        exec_._note_heavy_result([{}] * (exec_.HEAVY_RESULT_ROWS - 1), '清洗 #n1')
        assert spoken == []

    def test_a_large_result_names_the_node_and_the_count(self, exec_, spoken):
        exec_._note_heavy_result([{}] * exec_.HEAVY_RESULT_ROWS, '清洗 #n1')
        assert len(spoken) == 1, spoken
        assert '清洗 #n1' in spoken[0], 'an OOM with no node name is not a report'
        assert str(exec_.HEAVY_RESULT_ROWS) in spoken[0], spoken[0]

    def test_a_non_list_result_says_nothing(self, exec_, spoken):
        """A visualize/output node answers a DICT — a chart spec or a refusal — and there
        are no rows in it to hold, so announcing a memory cost would be a fabricated one.
        """
        exec_._note_heavy_result({'error': 'x'}, '可视化 #n2')
        assert spoken == []

    def test_the_notice_is_not_a_refusal(self, exec_, spoken):
        """It must not raise and must not change the rows: a big table is often exactly
        what was asked for, and the run is still the user's to finish."""
        rows = [{'a': 1}] * exec_.HEAVY_RESULT_ROWS
        exec_._note_heavy_result(rows, '清洗 #n1')
        assert len(rows) == exec_.HEAVY_RESULT_ROWS
