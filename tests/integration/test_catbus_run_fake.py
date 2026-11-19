"""One full CatBus run against a fake adapter CLI, end to end.

The fast tier stubs :func:`services.ingest.catbus._call` and the real-CLI tier talks to a machine's
actual adapter. This file sits between them: a child process that speaks the adapter's **wire
contract** (capabilities JSON on stdout, JSONL rows on stdout, one summary envelope on stderr) is
driven through discovery and :func:`bridge.run`, so a change to the argv, the stdin payload or the
column check that only shows up across a process boundary is caught here without a real catbus.

No site is contacted and no account is spent — the fake prints what the test told it to print.
"""

import sys
import textwrap

import pytest

from services.ingest import catbus as bridge

pytestmark = pytest.mark.integration

MANIFEST = {
    'schema': 1,
    'backend': 'catbus',
    'platforms': {
        'bilibili': {
            'catbus_platform': 'bilibili',
            'label': 'B站',
            'modes': {
                'posts': {
                    'status': 'available',
                    'columns': ['标题', '链接'],
                    'identity': ['链接'],
                    'params': ['keyword', 'target_count', 'catbus_account'],
                    'auth': 'required',
                },
                'notice.count': {
                    'status': 'available',
                    'columns': ['平台', '未读总数', '系统'],
                    'identity': ['平台', '未读总数'],
                    'params': ['catbus_account'],
                    'auth': 'required',
                },
            },
        }
    },
}

# The fake adapter: argument shape, stdin params and stdout/stderr streams are the real contract.
# UTF-8 is reconfigured on both ends on Windows, where a pipe otherwise uses the ANSI code page.
FAKE_ADAPTER = textwrap.dedent(
    """
    import json, sys
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if args[-1:] == ['--version']:
        sys.stdout.write('v24.21.0\\n'); sys.exit(0)
    if 'capabilities' in args:
        sys.stdout.write(json.dumps(MANIFEST, ensure_ascii=False) + '\\n'); sys.exit(0)
    if 'run' in args:
        params = json.loads(sys.stdin.read() or '{}')
        mode = args[args.index('--mode') + 1] if '--mode' in args else ''
        if mode == 'notice.count':
            rows = [{'平台': 'bilibili', '未读总数': 3, '系统': 1}]
        else:
            rows = [{'标题': '甲', '链接': 'u1'}, {'标题': '乙', '链接': 'u2'}]
        for row in rows:
            sys.stdout.write(json.dumps(row, ensure_ascii=False) + '\\n')
        sys.stdout.flush()
        sys.stderr.write(json.dumps({
            'backend': 'catbus', 'status': 'ok', 'rows': len(rows), 'warnings': [], 'articles': [],
        }, ensure_ascii=False) + '\\n')
        sys.exit(0)
    sys.exit(2)
    """
)


@pytest.fixture
def fake_backend(monkeypatch, tmp_path):
    script = tmp_path / 'fake-adapter.py'
    script.write_text('MANIFEST = ' + repr(MANIFEST) + '\n' + FAKE_ADAPTER, encoding='utf-8')
    monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': sys.executable)
    monkeypatch.setattr(bridge.machine, 'find_catbus_cli', lambda explicit='': str(script))
    # The stand-in answers ``--version`` with Python's own version; that is not a Node gate to apply.
    monkeypatch.setattr(bridge.machine, 'node_version_supported', lambda version: True)
    # A Python stand-in is not one of the script suffixes; call it with this interpreter directly.
    monkeypatch.setattr(bridge, 'argv_for', lambda node, entry, args: [sys.executable, entry, *args])
    bridge.reset_probe_cache()
    yield
    bridge.reset_probe_cache()


class TestAFullRunThroughTheWireContract:
    def test_discovery_reads_the_fake_manifest(self, fake_backend):
        info = bridge.probe(force=True)
        assert info.available
        assert info.platforms == ('bilibili',)
        assert bridge.supports('bilibili', 'notice.count')

    def test_a_list_mode_streams_rows_the_manifest_declares(self, fake_backend):
        got = []
        outcome = bridge.run('bilibili', 'posts', {'keyword': '露营', 'target_count': 2}, on_row=got.append)
        assert outcome.status == 'ok'
        assert outcome.rows == 2
        assert [row['标题'] for row in got] == ['甲', '乙']

    def test_the_full_functionality_mode_keeps_its_non_table_columns(self, fake_backend):
        got = []
        outcome = bridge.run('bilibili', 'notice.count', {}, on_row=got.append)
        assert outcome.status == 'ok', outcome.message
        assert outcome.rows == 1
        assert got == [{'平台': 'bilibili', '未读总数': 3, '系统': 1}]

    def test_a_column_drift_from_the_child_is_a_named_refusal(self, fake_backend, monkeypatch):
        original = bridge._call

        def drifted(argv, **kw):
            on_line = kw.get('on_line')
            if on_line is not None:
                kw['on_line'] = lambda line: on_line(line.replace('未读总数', 'total'))
            return original(argv, **kw)

        monkeypatch.setattr(bridge, '_call', drifted)
        outcome = bridge.run('bilibili', 'notice.count', {})
        assert outcome.status == 'error'
        assert '未读总数' in outcome.message
