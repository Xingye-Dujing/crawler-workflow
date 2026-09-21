"""Batch row-runner tests for analyzers/llm_client.py (run_llm_rows / run_llm_dataframe).

This is the machinery that decides whether a half-finished LLM run survives:
per-row checkpointing, replay-on-resume, the circuit breaker, cancellation,
and the 未处理 marker for rows that never landed. Everything here runs against
a scripted client (``chat`` overridden) — no sockets, no daemon, by design.
"""
import contextlib

import pytest

from analyzers.llm_client import (
    ABORT_MARK,
    LLMClient,
    LLMError,
    RowCheckpoint,
    content_key,
    run_llm_dataframe,
    run_llm_rows,
    text_hash,
)

pytestmark = pytest.mark.unit


def parse_emotion(content):
    """The real emotion.py contract: 'Emotion: pos\\nConfidence: 0.9' -> ('pos', 0.9),
    unparseable -> (None, 0.0)."""
    label = ''
    confidence = 0.0
    for line in content.splitlines():
        if line.startswith('Emotion:'):
            label = line.split(':', 1)[1].strip().lower()
        elif line.startswith('Confidence:'):
            with contextlib.suppress(ValueError):
                confidence = float(line.split(':', 1)[1])
    if label not in ('pos', 'neg', 'neutral'):
        return None, 0.0
    return label, confidence


def build_prompt(text):
    return f'classify sentiment: {text}'


class ScriptedClient(LLMClient):
    """A real LLMClient (so truncate() semantics are the production ones) whose
    transport is a script. Replies derive from the prompt so parallel workers
    are deterministic; failure knobs raise instead of answering."""

    def __init__(self, replies=None, error_after=None, exc=None, **kw):
        super().__init__(provider='openrouter', model='scripted', api_key='test-key', **kw)
        self.replies = dict(replies or {})
        self.default_reply = 'Emotion: pos\nConfidence: 0.9'
        self.error_after = error_after  # raise transport LLMError after N chats
        self.exc = exc  # raise this exception class every row
        self.prompts = []

    def chat(self, prompt, max_retries=2):
        self.prompts.append(prompt)
        n = len(self.prompts)
        if self.error_after is not None and n > self.error_after:
            raise LLMError('transport died', 'network')
        if self.exc is not None:
            raise self.exc('row failed')
        return self.replies.get(prompt, self.default_reply)


JOBS = [(0, '三亚的海非常蓝'), (1, '海南粉的汤底鲜美'), (2, '小镇非常安静')]


def run_simple(jobs=None, **overrides):
    kwargs = {'client': ScriptedClient(), 'build_prompt': build_prompt, 'parse': parse_emotion}
    kwargs.update(overrides)
    return run_llm_rows(list(JOBS if jobs is None else jobs), **kwargs)


# ─── RowCheckpoint (JSONL fallback store) ───────────────────────────────


class TestRowCheckpoint:
    def test_add_get_roundtrip(self, tmp_path):
        cp = RowCheckpoint(str(tmp_path), 'emotion|ds1')
        cp.add(3, 'h3', ('pos', 0.8))
        assert cp.get(3, 'h3') == {'i': 3, 'h': 'h3', 'r': ['pos', 0.8]}
        assert cp.get(3, 'other-hash') is None  # re-crawled table must not inherit
        assert cp.get(4, 'h3') is None

    def test_reload_from_disk_ignores_corrupt_lines(self, tmp_path):
        cp = RowCheckpoint(str(tmp_path), 'k1')
        cp.add(0, 'h0', ('neg', 0.2))
        with open(cp.path, 'a', encoding='utf-8') as fh:
            fh.write('not json at all\n')
            fh.write('{"i": 9}\n')  # missing fields
        reopened = RowCheckpoint(str(tmp_path), 'k1')
        assert reopened.get(0, 'h0') is not None
        assert reopened.get(9, 'x') is None

    def test_discard_removes_the_file(self, tmp_path):
        cp = RowCheckpoint(str(tmp_path), 'k1')
        cp.add(0, 'h0', ('pos', 0.1))
        cp.discard()
        import os

        assert not os.path.exists(cp.path)
        cp.discard()  # already gone — must not raise

    def test_content_key_changes_with_text_order(self):
        assert content_key(['a', 'b']) != content_key(['b', 'a'])
        assert content_key(['a', 'b']) == content_key(['a', 'b'])


# ─── run_llm_rows ───────────────────────────────────────────────────────


class TestRunRows:
    def test_happy_path_applies_and_publishes_per_batch(self):
        applied = []
        publishes = []
        results = run_simple(
            jobs=list(JOBS),
            apply_result=lambda idx, res: applied.append(idx),
            publish=lambda: publishes.append(1),
            batch_size=2,
        )
        assert set(results) == {0, 1, 2}
        assert results[0] == ('pos', 0.9)
        assert applied == [0, 1, 2]
        assert len(publishes) == 2  # after batch of 2, then the tail batch

    def test_truncation_reaches_build_prompt(self):
        client = ScriptedClient(max_chars=5)
        run_llm_rows([(0, 'abcdefghij')], client, build_prompt, parse_emotion)
        assert client.prompts == ['classify sentiment: abcde…']

    def test_crash_then_resume_skips_finished_rows(self, tmp_path):
        first = ScriptedClient(error_after=2)  # dies on row 3
        cp = RowCheckpoint(str(tmp_path), 'emotion|qwen|正文|' + content_key([t for _i, t in JOBS]))
        with pytest.raises(LLMError):
            run_llm_rows(list(JOBS), first, build_prompt, parse_emotion, checkpoint=cp)
        assert len(first.prompts) == 3  # third call raised mid-flight
        # The two clean rows survived the crash:
        survivor = RowCheckpoint(str(tmp_path), 'emotion|qwen|正文|' + content_key([t for _i, t in JOBS]))
        assert survivor.get(0, text_hash('三亚的海非常蓝')) is not None
        assert survivor.get(2, text_hash('小镇非常安静')) is None  # never completed

        second = ScriptedClient()
        results = run_llm_rows(list(JOBS), second, build_prompt, parse_emotion, checkpoint=survivor)
        assert second.prompts == [build_prompt('小镇非常安静')]  # only the missing row re-paid
        assert set(results) == {0, 1, 2}

    def test_unparseable_rows_are_not_checkpointed(self, tmp_path):
        client = ScriptedClient(replies={build_prompt('三亚的海非常蓝'): 'garbage output'})
        cp = RowCheckpoint(str(tmp_path), 'cpkey')
        results = run_llm_rows(list(JOBS), client, build_prompt, parse_emotion, checkpoint=cp)
        assert 0 not in results  # (None, 0.0) is treated as failure
        assert cp.get(0, text_hash('三亚的海非常蓝')) is None
        assert cp.get(1, text_hash('海南粉的汤底鲜美')) is not None

    def test_circuit_breaker_stops_after_consecutive_failures(self):
        client = ScriptedClient(exc=RuntimeError)
        with pytest.raises(LLMError) as err:
            run_simple(jobs=[(i, f'text {i}') for i in range(8)], client=client, max_consecutive_failures=3)
        assert err.value.kind == 'circuit_break'
        # Each failing row double-counts (exception + failed result); the trip
        # happens at the next row's check, so exactly 2 rows were attempted.
        assert len(client.prompts) == 2

    def test_transport_error_propagates_and_publishes_partial(self):
        publishes = []
        client = ScriptedClient(error_after=1)
        with pytest.raises(LLMError) as err:
            run_simple(jobs=list(JOBS), client=client, publish=lambda: publishes.append(1))
        assert err.value.kind == 'network'
        assert len(publishes) == 1  # the death path still published

    def test_preset_cancel_event_raises_before_any_row(self):
        import threading

        ev = threading.Event()
        ev.set()
        with pytest.raises(LLMError) as err:
            run_simple(jobs=list(JOBS), cancel_event=ev)
        assert err.value.kind == 'cancelled'

    def test_cancel_midway_keeps_finished_rows(self, tmp_path):
        import threading

        ev = threading.Event()
        cp = RowCheckpoint(str(tmp_path), 'ck')

        def apply(idx, res):
            if idx == 1:
                ev.set()

        with pytest.raises(LLMError) as err:
            run_simple(jobs=list(JOBS), apply_result=apply, cancel_event=ev, checkpoint=cp)
        assert err.value.kind == 'cancelled'
        assert cp.get(0, text_hash(JOBS[0][1])) is not None
        assert cp.get(1, text_hash(JOBS[1][1])) is not None  # applied, then cancel bit
        assert cp.get(2, text_hash(JOBS[2][1])) is None

    def test_parallel_workers_complete_every_row(self):
        client = ScriptedClient()

        def reply_for(prompt):
            return 'Emotion: neg\nConfidence: 0.2' if '安静' in prompt else 'Emotion: pos\nConfidence: 0.7'

        client.replies = {build_prompt(t): reply_for(build_prompt(t)) for _i, t in JOBS}
        extra = [(10 + i, t) for i, (_j, t) in enumerate(JOBS)]
        results = run_simple(jobs=list(JOBS) + extra, client=client, workers=3, batch_size=2)
        assert len(results) == 6
        assert {r[0] for r in results.values()} == {'pos', 'neg'}


# ─── run_llm_dataframe ──────────────────────────────────────────────────


@pytest.fixture
def df_for_llm():
    import pandas as pd

    return pd.DataFrame(
        {
            '正文': ['三亚的海非常蓝，适合冬天度假', '小镇安静', '', '海南粉的汤底非常鲜美适合夏天',
                    '博鳌的小镇非常安静适合散步'],
        }
    )


def run_df(df, client=None, **ctx):
    base = {
        'result_columns': ['情感', '置信度'],
        'blank': ['', 0.0],
        'skip_value': ['跳过', 0.0],
        'fail_value': ['失败', 0.0],
    }
    kwargs = {
        'text_column': '正文',
        'op': 'emotion',
        'build_prompt': build_prompt,
        'parse': parse_emotion,
        'ctx': {'client': client or ScriptedClient(), **ctx},
        **base,
    }
    return run_llm_dataframe(df, **kwargs)


class TestDataframeRunner:
    def test_short_and_empty_rows_are_skipped(self, df_for_llm):
        client = ScriptedClient()
        df = run_df(df_for_llm, client=client)
        assert df.loc[1, '情感'] == '跳过'  # len < min_len(10)
        assert df.loc[2, '情感'] == ''  # blank never enters process_indices
        assert df.loc[0, '情感'] == 'pos' and df.loc[4, '情感'] == 'pos'
        assert len(client.prompts) == 3

    def test_clean_run_discards_the_checkpoint_file(self, df_for_llm, tmp_path):
        client = ScriptedClient()
        df = run_df(df_for_llm, client=client, checkpoint_dir=str(tmp_path))
        assert list(tmp_path.glob('*.jsonl')) == []  # written while running, gone after
        assert (df.loc[4, '情感'], df.loc[4, '置信度']) == ('pos', 0.9)

    def test_transport_death_marks_unprocessed_and_reraises(self, df_for_llm):
        published = []
        client = ScriptedClient(error_after=0)  # first row already dies
        # cfg['publish'] receives the frame, matching how app.py wires it.
        with pytest.raises(LLMError):
            run_df(df_for_llm, client=client, publish=lambda _df: published.append(1))
        assert df_for_llm.loc[0, '情感'] == ABORT_MARK
        assert df_for_llm.loc[1, '情感'] == '跳过'  # skip marks stay skips
        assert published, 'partial results must be published before the raise'

    def test_cancel_is_swallowed_but_gap_stays_visible(self, df_for_llm):
        import threading

        ev = threading.Event()
        ev.set()
        df = run_df(df_for_llm, cancel_event=ev)  # no raise for cancelled
        for idx in (0, 3, 4):
            assert df.loc[idx, '情感'] == ABORT_MARK
        assert df.loc[1, '情感'] == '跳过'

    def test_missing_text_column_returns_blank_filled_frame(self, df_for_llm):
        client = ScriptedClient()
        df = run_llm_dataframe(
            df_for_llm,
            text_column='不存在',
            op='emotion',
            result_columns=['情感', '置信度'],
            blank=['', 0.0],
            skip_value=('跳过', 0.0),
            fail_value=('失败', 0.0),
            build_prompt=build_prompt,
            parse=parse_emotion,
            ctx={'client': client},
        )
        assert client.prompts == []
        assert (df['情感'] == '').all()

    def test_durable_cache_wins_over_jsonl(self, df_for_llm, tmp_path):
        # cfg['cache'] (the RowCache adapter over runs.db) must suppress the
        # JSONL path entirely, even when a checkpoint_dir is handed over.
        class SpyCache:
            def __init__(self):
                self.added = []

            def get(self, idx, thash):
                return None

            def add(self, idx, thash, result):
                self.added.append(idx)

            def discard(self):
                self.discarded = True

        spy = SpyCache()
        df = run_df(df_for_llm, cache=spy, checkpoint_dir=str(tmp_path))
        assert spy.added == [0, 3, 4]
        assert list(tmp_path.glob('*.jsonl')) == []
        # Clean finish calls discard() on whichever checkpoint object it got —
        # for the durable cache that is a no-op by contract, but it must not
        # raise, and the run must complete.
        assert getattr(spy, 'discarded', False) is True
        assert (df.loc[0, '情感'], df.loc[4, '情感']) == ('pos', 'pos')
