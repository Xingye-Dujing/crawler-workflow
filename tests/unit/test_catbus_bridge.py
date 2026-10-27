"""The CatBus bridge, tested without CatBus.

Everything this module decides is decided from an argv, a JSONL stream and a stderr summary, so the
fast tier drives those three directly: a stubbed capability manifest for the verdicts, and the suite's
own Python interpreter as the child process for the one thing that cannot be stubbed — that bytes
another process wrote arrive as the rows they were written as, on whichever platform ran the test. No
case here needs Node, CatBus, or a login; the tier that does is ``live_quick``.
"""

import json
import sys
import textwrap

import pytest
from core.config import Config

import settings_store
from i18n import get_lang, set_lang, t
from services import catbus_bridge as bridge

#: A trimmed copy of what ``catbus-crawler-workflow capabilities`` answers: the real shape, the real
# statuses, and only the entries a test asks about.
MANIFEST = {
    'schema': 1,
    'backend': 'catbus',
    'platforms': {
        'bilibili': {
            'catbus_platform': 'bilibili',
            'label': 'B站',
            'modes': {
                'posts': {'status': 'available', 'columns': ['标题', '链接'], 'reason': ''},
                'hot': {'status': 'partial', 'columns': ['标题', '链接'], 'reason': 'ranking 未接入'},
                'comments': {'status': 'available', 'columns': ['平台', '评论ID', '评论内容'], 'reason': ''},
            },
        },
        'weibo': {
            'modes': {
                'hot': {'status': 'unavailable', 'reason': 'CatBus 没有注册微博热搜'},
                'comments': {'status': 'planned', 'reason': '列映射未实现'},
            }
        },
    },
}

_REAL_PROBE_NOW = bridge._probe_now
_REAL_CALL = bridge._call


def a_probe(**kw):
    return bridge.Probe(
        available=kw.get('available', True),
        reason_key=kw.get('reason_key', ''),
        reason_params=kw.get('reason_params', {}),
        node=kw.get('node', '/usr/bin/node'),
        entry=kw.get('entry', '/opt/catbus/cli.js'),
        node_version='v24.21.0',
        manifest=kw.get('manifest', MANIFEST),
    )


def answer(version='v24.21.0', capabilities=None, code=0, record=None):
    """A stand-in for the two probe commands: the runtime's version, then the adapter's manifest."""

    def fake(argv, **kw):
        if record is not None:
            record.append(list(argv))
        if argv and argv[-1] == '--version':
            return bridge._Call(code=code, stdout=version, stderr='')
        blob = capabilities if capabilities is not None else json.dumps(MANIFEST, ensure_ascii=False)
        return bridge._Call(code=code, stdout=blob, stderr='')

    return fake


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    """Discovery and every command are stubbed: no fast case may spawn Node."""
    monkeypatch.setattr(bridge, '_probe_now', a_probe)
    monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=0, stdout='', stderr=''))
    bridge.reset_probe_cache()
    yield
    bridge.reset_probe_cache()


def summary_payload(**fields):
    """One adapter summary, exactly as it is printed on stderr."""
    base = {'ok': True, 'backend': 'catbus', 'endpoint': 'web', 'status': 'ok', 'rows': 0}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


@pytest.fixture
def restore_lang():
    """The message language is thread-local state; a case that pins it hands back what it found."""
    before = get_lang()
    yield
    set_lang(before)


class TestTheCommandShape:
    def test_a_script_entry_runs_on_node(self):
        assert bridge.argv_for('/usr/bin/node', '/opt/catbus/cli.js', ['capabilities']) == [
            '/usr/bin/node',
            '/opt/catbus/cli.js',
            'capabilities',
        ]

    def test_any_other_entry_is_the_program_itself(self):
        # A user who points CATBUS_CLI at a wrapper keeps the wrapper: an explicit path is the answer,
        # not a hint this side is free to rewrite into a script nobody asked for.
        assert bridge.argv_for('/usr/bin/node', '/opt/bin/catbus-crawler-workflow', ['-h']) == [
            '/opt/bin/catbus-crawler-workflow',
            '-h',
        ]

    def test_a_script_suffix_is_matched_without_case(self):
        assert bridge.argv_for('node', 'CLI.MJS', []) == ['node', 'CLI.MJS']
        assert bridge.argv_for('node', 'wrapper', []) == ['wrapper']

    def test_the_suffix_that_chooses_node_is_the_suffix_that_chooses_the_disk_test(self):
        """One list, read by both sides: the argv builder and the finder must not disagree about
        whether an entry is a script, or a readable-but-not-executable ``cli.js`` would be found by
        one and refused by the other."""
        assert bridge._SCRIPT_SUFFIXES == bridge.machine.CATBUS_SCRIPT_SUFFIXES

    def test_the_nodes_account_never_reaches_the_adapter(self):
        """The node's 账号 selects a Selenium session; CatBus has its own account files."""
        payload = bridge._params_payload({'keyword': '键盘', 'account': 'work', 'recrawl': True}, '')
        assert 'account' not in payload
        assert 'catbus_account' not in payload
        assert payload['keyword'] == '键盘'
        assert payload['recrawl'] is True, 'execution-layer fields stay in the payload that ignores them'

    def test_the_catbus_account_is_the_one_asked_for(self):
        assert bridge._params_payload({'account': 'selenium-login'}, 'catbus-work') == {'catbus_account': 'catbus-work'}


class TestTheDiscoveryVerdict:
    """These cases ARE the discovery logic, so they put the real one back over the stub."""

    @pytest.fixture(autouse=True)
    def _real_logic(self, monkeypatch):
        monkeypatch.setattr(bridge, '_probe_now', _REAL_PROBE_NOW)
        monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': '/usr/bin/node')
        monkeypatch.setattr(bridge.machine, 'find_catbus_cli', lambda explicit='': '/opt/catbus/cli.js')

    def test_no_node_is_named_as_no_node(self, monkeypatch):
        monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': '')
        info = bridge.probe(force=True)
        assert not info.available
        assert info.reason_key == 'catbus.noNode'

    def test_a_machine_with_node_but_no_adapter_says_so(self, monkeypatch):
        monkeypatch.setattr(bridge.machine, 'find_catbus_cli', lambda explicit='': '')
        monkeypatch.setattr(bridge, '_call', answer())
        info = bridge.probe(force=True)
        assert info.reason_key == 'catbus.noCli', '「装了 Node」 and 「装了 CatBus」 are two separate facts'

    def test_an_old_runtime_is_refused_before_it_fails_obscurely(self, monkeypatch):
        seen = []
        monkeypatch.setattr(bridge, '_call', answer(version='v18.20.4\n', record=seen))
        info = bridge.probe(force=True)
        assert info.reason_key == 'catbus.oldNode'
        assert info.reason_params['version'] == 'v18.20.4'
        assert seen == [['/usr/bin/node', '--version']], 'the version is asked of the runtime, not the adapter'

    def test_the_adapter_is_asked_for_its_own_manifest(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bridge, '_call', answer(record=calls))
        info = bridge.probe(force=True)
        assert info.available
        assert calls[-1] == ['/usr/bin/node', '/opt/catbus/cli.js', 'capabilities']
        assert info.platforms == ('bilibili', 'weibo')

    def test_the_paths_the_panel_saved_are_the_paths_discovery_asks_about(self, monkeypatch):
        """The last mile of the settings field: a path typed into 设置 has to reach the finder.

        ``Config.CATBUS_*`` (the environment) is the fallback, never the answer — and the two are
        indistinguishable from a unit test that only stubs the finder, so the finders are asked what
        string they were handed.
        """
        asked = []
        monkeypatch.setattr(
            settings_store,
            'get_setting',
            lambda key: {'catbus_node': '/opt/nvm/v24/bin/node', 'catbus_cli': '/srv/catbus'}.get(key, ''),
        )
        monkeypatch.setattr(Config, 'CATBUS_NODE', '/should/not/be/read')
        monkeypatch.setattr(Config, 'CATBUS_CLI', '/should/not/be/read')
        monkeypatch.setattr(
            bridge.machine,
            'find_node',
            lambda explicit='': asked.append(('node', explicit)) or '/opt/nvm/v24/bin/node',
        )
        monkeypatch.setattr(
            bridge.machine,
            'find_catbus_cli',
            lambda explicit='': asked.append(('cli', explicit)) or '/opt/catbus/cli.js',
        )
        monkeypatch.setattr(bridge, '_call', answer())
        info = bridge.probe(force=True)
        assert asked == [('node', '/opt/nvm/v24/bin/node'), ('cli', '/srv/catbus')]
        assert info.entry == '/opt/catbus/cli.js'

    def test_an_empty_field_hands_the_environment_to_discovery(self, monkeypatch):
        """「留空=自动」 means the env default and then the per-OS tables, not 「nothing configured」."""
        asked = []
        monkeypatch.setattr(settings_store, 'get_setting', lambda key: '')
        monkeypatch.setattr(Config, 'CATBUS_NODE', '')
        monkeypatch.setattr(Config, 'CATBUS_CLI', '/env/only/cli.js')
        monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': '/usr/bin/node')
        monkeypatch.setattr(
            bridge.machine,
            'find_catbus_cli',
            lambda explicit='': asked.append(explicit) or '/env/only/cli.js',
        )
        monkeypatch.setattr(bridge, '_call', answer())
        assert bridge.probe(force=True).available
        assert asked == ['/env/only/cli.js']

    def test_a_failing_probe_is_a_named_reason(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', answer(capabilities='', code=1))
        assert bridge.probe(force=True).reason_key == 'catbus.probeFailed'

    def test_an_unreadable_manifest_is_a_named_reason(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', answer(capabilities='not json'))
        assert bridge.probe(force=True).reason_key == 'catbus.probeUnreadable'

    def test_the_verdict_is_cached_and_reasked_on_demand(self, monkeypatch):
        asked = []

        def fake_now():
            asked.append(1)
            return a_probe()

        monkeypatch.setattr(bridge, '_probe_now', fake_now)
        bridge.probe()
        bridge.probe()
        assert len(asked) == 1, 'a page load must not spawn a Node process per canvas'
        bridge.probe(force=True)
        assert len(asked) == 2

    def test_the_reason_renders_in_the_language_that_asks(self, monkeypatch, restore_lang):
        monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': '')
        key = bridge.probe(force=True).reason_key
        set_lang('zh')
        assert t(key) != key, 'a refusal that prints its own key is a printed bug'
        set_lang('en')
        assert 'Node' in t(key)


class TestTheManifestIsTheOnlyOpinion:
    def test_a_supported_cell_is_supported(self):
        assert bridge.supports('bilibili', 'posts')
        assert bridge.supports('bilibili', 'hot'), 'partial still crawls, with the adapters own reason kept'
        assert bridge.columns_for('bilibili', 'comments') == ('平台', '评论ID', '评论内容')

    def test_an_unsupported_cell_keeps_the_adapters_own_words(self):
        status, reason = bridge.mode_state('weibo', 'hot')
        assert status == 'unavailable'
        assert reason == 'CatBus 没有注册微博热搜', 'the reason is the adapters sentence, not one written here'

    def test_a_planned_cell_is_not_runnable(self):
        assert not bridge.supports('weibo', 'comments')

    def test_the_verdict_and_its_reason_arrive_together(self):
        """A refusal prints the reason belonging to the state it refused on.

        The crawler's gate used to ask ``mode_state`` for the status and again for the sentence, so a
        re-probe between the two could print a reason for a cell that is not the one being refused.
        """
        runnable, why = bridge.crawlability('weibo', 'hot')
        assert runnable is False
        assert why == 'CatBus 没有注册微博热搜'
        assert bridge.crawlability('bilibili', 'posts')[0] is True

    def test_a_cell_the_manifest_does_not_list_is_reported_as_absent(self):
        status, reason = bridge.mode_state('zhihu', 'posts')
        assert status == 'unavailable'
        # The platform is named with a word, not the key the manifest is indexed by, and the reason is
        # this project's own sentence about an absent cell — never an empty result.
        assert reason == t('catbus.notInManifest', platform='zhihu', mode='posts')
        assert 'zhihu' not in reason and '知乎' in reason

    def test_an_unavailable_backend_refuses_every_cell_by_name(self, monkeypatch):
        monkeypatch.setattr(bridge, 'probe', lambda force=False: a_probe(available=False, reason_key='catbus.noNode'))
        assert not bridge.supports('bilibili', 'posts')
        assert 'Node' in bridge.mode_state('bilibili', 'posts')[1]


class TestRunTranslatesTheAdapter:
    """``run`` never invents a row count, and never lets a failure read as "the site had nothing"."""

    @staticmethod
    def _stream(rows, summary, code=0, stopped=False, timed_out=False):
        def fake_call(argv, **kw):
            on_line = kw.get('on_line')
            for row in rows:
                on_line(json.dumps(row, ensure_ascii=False))
            return bridge._Call(code=code, stderr=summary, stopped=stopped, timed_out=timed_out)

        return fake_call

    def test_rows_are_handed_over_as_they_arrive_and_counted(self, monkeypatch):
        got = []
        monkeypatch.setattr(
            bridge,
            '_call',
            self._stream([{'标题': '甲', '链接': 'u1'}, {'标题': '乙', '链接': 'u2'}], summary_payload(rows=2)),
        )
        outcome = bridge.run('bilibili', 'posts', {'keyword': '甲'}, on_row=got.append)
        assert outcome.status == 'ok'
        assert outcome.rows == 2
        assert [row['标题'] for row in got] == ['甲', '乙']

    def test_the_params_reach_the_child_as_one_utf8_document(self, monkeypatch):
        captured = {}

        def fake_call(argv, **kw):
            captured['argv'] = argv
            captured['stdin'] = kw.get('stdin_text')
            return bridge._Call(code=0, stderr=summary_payload())

        monkeypatch.setattr(bridge, '_call', fake_call)
        bridge.run('bilibili', 'posts', {'keyword': '露营', 'target_count': 20}, account='catbus-work')
        assert captured['argv'] == [
            '/usr/bin/node',
            '/opt/catbus/cli.js',
            'run',
            '--platform',
            'bilibili',
            '--mode',
            'posts',
            '--params',
            '-',
        ]
        # A Chinese keyword and a long URL list must not be encoded by a console code page or cut off
        # by a command-line length limit, so they travel as one UTF-8 document on stdin.
        assert json.loads(captured['stdin']) == {'keyword': '露营', 'target_count': 20, 'catbus_account': 'catbus-work'}

    def test_a_blocked_summary_with_a_nonzero_exit_stays_blocked(self, monkeypatch):
        """The comments case that matters: exit 3, one article kept, the next one walled."""
        summary = summary_payload(
            ok=False,
            status='blocked',
            rows=1,
            warnings=['u2: AUTH_REQUIRED 未登录'],
            articles=[
                {'url': 'u1', 'status': 'ok', 'rows': 1, 'error': None},
                {'url': 'u2', 'status': 'blocked', 'rows': 0, 'error': {'code': 'AUTH_REQUIRED'}},
            ],
        )
        monkeypatch.setattr(
            bridge,
            '_call',
            self._stream([{'平台': 'bilibili', '评论ID': '9', '评论内容': '好'}], summary, code=3),
        )
        outcome = bridge.run('bilibili', 'comments', {'urls': ['u1', 'u2']})
        assert outcome.status == 'blocked'
        assert outcome.rows == 1, 'the row that landed is not un-counted because another article was walled'
        assert [a.status for a in outcome.articles] == ['ok', 'blocked']
        assert outcome.warnings == ('u2: AUTH_REQUIRED 未登录',)

    def test_a_partial_run_reports_which_links_it_lost(self, monkeypatch):
        summary = summary_payload(
            status='partial',
            rows=1,
            warnings=['BV1: UPSTREAM 404'],
            articles=[{'url': 'BV1', 'status': 'dead', 'rows': 0, 'error': {'code': 'UPSTREAM'}}],
        )
        monkeypatch.setattr(bridge, '_call', self._stream([{'标题': '甲', '链接': 'u'}], summary))
        outcome = bridge.run('bilibili', 'posts', {'keyword': '甲'})
        assert outcome.status == 'partial'
        assert outcome.articles[0].status == 'dead'

    def test_a_refused_cell_never_starts_a_process(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: calls.append(argv) or bridge._Call(code=0))
        outcome = bridge.run('weibo', 'hot', {})
        assert outcome.status == 'error'
        assert outcome.message == 'CatBus 没有注册微博热搜'
        assert calls == []

    def test_a_column_that_moved_is_refused_by_name(self, monkeypatch):
        """An upstream rename is a named refusal, not a table the charts silently misread."""
        monkeypatch.setattr(
            bridge,
            '_call',
            self._stream([{'标题': '甲', 'url': 'u1'}], summary_payload(rows=1)),
        )
        outcome = bridge.run('bilibili', 'posts', {'keyword': '甲'})
        assert outcome.status == 'error'
        assert '链接' in outcome.message and 'url' in outcome.message

    def test_a_line_that_is_not_a_row_is_refused_not_dropped(self, monkeypatch):
        def fake_call(argv, **kw):
            kw['on_line']('{"标题": ')
            return bridge._Call(code=0, stderr=summary_payload())

        monkeypatch.setattr(bridge, '_call', fake_call)
        assert bridge.run('bilibili', 'posts', {'keyword': '甲'}).status == 'error'

    def test_a_stopped_run_keeps_its_rows_and_says_it_was_stopped(self, monkeypatch):
        rows = [{'标题': '甲', '链接': 'u'}]
        monkeypatch.setattr(
            bridge,
            '_call',
            self._stream(rows, summary_payload(status='partial', rows=1), code=130, stopped=True),
        )
        outcome = bridge.run('bilibili', 'posts', {'keyword': '甲'})
        assert outcome.status == 'stopped'
        assert outcome.rows == 1

    def test_no_summary_is_the_childs_own_report(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=7, stderr='boom\nupstream 404'))
        outcome = bridge.run('bilibili', 'posts', {'keyword': '甲'})
        assert outcome.status == 'error'
        assert 'upstream 404' in outcome.message, 'the last line the child said, not a bare exit code'

    def test_a_timeout_names_the_deadline(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=-1, timed_out=True))
        assert str(bridge.RUN_TIMEOUT) in bridge.run('bilibili', 'posts', {'keyword': '甲'}).message

    def test_the_summary_is_the_last_catbus_object_on_stderr(self):
        call = bridge._Call(
            code=0,
            stderr='[catbus] 一些日志\n'
            + summary_payload(status='other', backend='other')
            + '\n'
            + summary_payload(rows=3),
        )
        assert bridge._summary_of(call)['rows'] == 3


class TestPreflightAsksCatBusAlone:
    def test_a_logged_in_verdict_keeps_the_account_and_method(self, monkeypatch):
        verdict = {
            'ok': True,
            'platform': 'bilibili',
            'account': 'catbus-work',
            'logged_in': True,
            'user': {'name': '猫'},
            'method': 'qrcode',
            'expires_at': None,
            'error': None,
        }
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=0, stdout=json.dumps(verdict)))
        out = bridge.preflight('bilibili', 'catbus-work')
        assert out['logged_in'] is True
        assert out['verdict'] == 'valid'
        assert out['account'] == 'catbus-work'

    def test_an_absent_login_carries_the_login_command_as_the_hint(self, monkeypatch):
        verdict = {
            'logged_in': False,
            'account': None,
            'error': {'message': 'CatBus 未登录 B站 (web)', 'hint': 'catbus bilibili auth login'},
        }
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=3, stdout=json.dumps(verdict)))
        out = bridge.preflight('bilibili')
        assert out['logged_in'] is False
        assert out['verdict'] == 'expired'
        assert out['hint'] == 'catbus bilibili auth login', 'the remedy names CatBus, never a Selenium cookie'

    def test_the_account_is_asked_of_by_name(self, monkeypatch):
        seen = []

        def fake_call(argv, **kw):
            seen.append(list(argv))
            return bridge._Call(code=0, stdout=json.dumps({'logged_in': True}))

        monkeypatch.setattr(bridge, '_call', fake_call)
        bridge.preflight('bilibili', 'catbus-work')
        assert seen[0][-4:] == ['--platform', 'bilibili', '--account', 'catbus-work']

    def test_a_machine_without_the_backend_cannot_be_asked(self, monkeypatch):
        monkeypatch.setattr(bridge, 'probe', lambda force=False: a_probe(available=False, reason_key='catbus.noCli'))
        out = bridge.preflight('bilibili')
        assert out['verdict'] == 'unverifiable', '「cannot ask」 is not 「not logged in」'
        assert 'CatBus' in out['message']

    def test_a_spawn_that_failed_is_unverifiable_not_expired(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=-1, spawn_error='no such file'))
        assert bridge.preflight('bilibili')['verdict'] == 'unverifiable'

    def test_an_unreadable_verdict_is_unverifiable(self, monkeypatch):
        monkeypatch.setattr(bridge, '_call', lambda argv, **kw: bridge._Call(code=0, stdout='<html>502</html>'))
        assert bridge.preflight('bilibili')['verdict'] == 'unverifiable'


class TestTheRealSubprocessBoundary:
    """The one case that is not stubbed: the pipes, the encoding and the deadline of a live child.

    The child is the suite's own interpreter, so the same fact is proven on Windows, Linux and macOS
    — that a UTF-8 row another process wrote arrives as that row, and that a child which stops
    answering is taken down instead of waited on forever.
    """

    @pytest.fixture(autouse=True)
    def _real_spawn(self, monkeypatch):
        """The stub above replaces :func:`_call`; these cases are about what it really does."""
        monkeypatch.setattr(bridge, '_call', _REAL_CALL)

    SCRIPT = textwrap.dedent(
        """
        import json, sys
        # A child that speaks UTF-8 through a pipe must SAY so, on both ends. On Windows a piped
        # ``sys.stdin``/``sys.stdout`` uses the ANSI code page (cp936 on this box) unless it is
        # reconfigured, which is the trap the bridge refuses to fall into by writing and decoding
        # bytes itself instead of trusting a locale. Node — the adapter this test stands in for —
        # reads and writes UTF-8 unconditionally.
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        payload = json.loads(sys.stdin.read() or '{}')
        for title in payload['titles']:
            sys.stdout.write(json.dumps({'标题': title, '链接': 'u'}, ensure_ascii=False) + '\\n')
            sys.stdout.flush()
        sys.stderr.write(json.dumps({'backend': 'catbus', 'status': 'ok', 'rows': 2}) + '\\n')
        """
    )

    def test_a_child_streaming_utf8_rows_arrives_row_by_row(self):
        got = []
        call = bridge._call(
            [sys.executable, '-c', self.SCRIPT],
            stdin_text=json.dumps({'titles': ['甲', '乙']}, ensure_ascii=False),
            on_line=got.append,
        )
        assert call.code == 0, call.stderr
        assert [json.loads(line)['标题'] for line in got] == ['甲', '乙']
        assert bridge._summary_of(call)['status'] == 'ok'

    def test_a_child_that_stops_answering_is_killed_at_the_deadline(self):
        script = 'import time\nwhile True: time.sleep(0.2)'
        call = bridge._call([sys.executable, '-c', script], capture=True, timeout=1.0)
        assert call.timed_out is True

    def test_an_abort_between_rows_stops_the_child_and_reports_it(self):
        seen = []

        def abort():
            return len(seen) >= 1

        call = bridge._call(
            [sys.executable, '-c', self.SCRIPT],
            stdin_text=json.dumps({'titles': ['甲', '乙']}, ensure_ascii=False),
            on_line=seen.append,
            abort=abort,
        )
        assert call.stopped is True
        assert len(seen) == 1, 'the row already in hand is kept; the next one is not asked for'
