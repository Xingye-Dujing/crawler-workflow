"""CatBus in the AI workspace: read-only detection, the local-only skill and its routing.

No case here needs Node or a real catbus install — the detection tool reports what it is *told* the
machine has, and the skill's contract is text. The real adapter's own matrix is covered by the
integration tier; this file pins the AI-side seam so a prompt or tool rename fails fast.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def bridge(monkeypatch):
    from services.ingest import catbus as module

    return module


def test_catbus_status_reports_two_facts_without_installing(monkeypatch, bridge):
    from ai import tools

    info = bridge.Probe(
        available=True,
        node='/opt/node',
        node_version='v24.21.0',
        entry='/opt/catbus/cli.js',
        manifest={'platforms': {'bilibili': {}, 'xiaohongshu': {}}},
    )
    seen = []
    monkeypatch.setattr(bridge, 'probe', lambda force=False: info)
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/catbus' if name == 'catbus' else None)

    def fake_version(path, node=''):
        seen.append([path, 'version'])
        return 'catbus 0.3.0'

    monkeypatch.setattr(bridge, 'executable_version', fake_version)

    out = tools.tool_catbus_status({}, {})

    assert out['available'] is True
    assert out['reason_key'] == ''
    assert out['entry'] == '/opt/catbus/cli.js'
    assert out['platforms'] == ['bilibili', 'xiaohongshu']
    assert out['cli_ok'] is True and out['cli_version'] == 'catbus 0.3.0'
    assert seen == [['/usr/bin/catbus', 'version']], 'detection reads, it never installs'
    assert 'Both paths are ready' in out['hint']


def test_catbus_status_names_the_missing_part(monkeypatch, bridge):
    from ai import tools

    info = bridge.Probe(available=False, reason_key='catbus.noCli', reason_params={}, manifest={})
    monkeypatch.setattr(bridge, 'probe', lambda force=False: info)
    monkeypatch.setattr('shutil.which', lambda name: None)

    out = tools.tool_catbus_status({}, {})

    assert out['available'] is False
    assert out['reason_key'] == 'catbus.noCli'
    assert out['message'], 'a refusal is a named reason, not a silent empty'
    assert out['cli'] == '' and out['cli_ok'] is False
    # The canvas backend itself is unavailable, so the hint names that — it does not push an install.
    assert 'unavailable' in out['hint'].lower() and 'do not install' in out['hint']


def test_local_checkout_is_found_from_the_adapter_path_without_env_vars(monkeypatch, bridge, tmp_path):
    """A built checkout counts as present — no CATBUS_BIN/CATBUS_HOME and no install required."""
    main = tmp_path / 'dist' / 'cli' / 'main.js'
    main.parent.mkdir(parents=True)
    main.write_text('// a local build', encoding='utf-8')
    entry = tmp_path / 'dist' / 'integrations' / 'crawler-workflow' / 'cli.js'
    monkeypatch.delenv('CATBUS_BIN', raising=False)
    monkeypatch.delenv('CATBUS_HOME', raising=False)

    from services.ingest import catbus_toolchain as toolchain

    root, found = toolchain.local_checkout(str(entry))

    assert root == str(tmp_path) and found == str(main)


def test_executable_version_runs_a_script_through_node(monkeypatch, bridge):
    seen = []
    monkeypatch.setattr(bridge.machine, 'find_node', lambda explicit='': '/usr/bin/node')
    monkeypatch.setattr(
        bridge,
        '_call',
        lambda argv, **kw: seen.append(list(argv)) or bridge._Call(code=0, stdout='catbus 0.3.0\n', stderr=''),
    )

    assert bridge.executable_version('/opt/catbus/dist/cli/main.js') == 'catbus 0.3.0'
    assert seen == [['/usr/bin/node', '/opt/catbus/dist/cli/main.js', 'version']]


def test_catbus_status_offers_local_build_or_install(monkeypatch, bridge, tmp_path):
    """No global CLI but a local build: the tool reports both and tells the AI to ASK."""
    from ai import tools

    main = tmp_path / 'dist' / 'cli' / 'main.js'
    main.parent.mkdir(parents=True)
    main.write_text('// a local build', encoding='utf-8')
    entry = tmp_path / 'dist' / 'integrations' / 'crawler-workflow' / 'cli.js'
    info = bridge.Probe(available=True, node='/opt/node', node_version='v24', entry=str(entry), manifest={})
    monkeypatch.setattr(bridge, 'probe', lambda force=False: info)
    monkeypatch.setattr('shutil.which', lambda name: None)
    monkeypatch.delenv('CATBUS_BIN', raising=False)
    monkeypatch.delenv('CATBUS_HOME', raising=False)
    monkeypatch.setattr(bridge, 'executable_version', lambda path, node='': 'catbus 0.3.0 (local)')

    out = tools.tool_catbus_status({}, {})

    assert out['cli'] == '' and out['cli_ok'] is False, 'a local build is not a global install'
    assert out['local_root'] == str(tmp_path) and out['local_cli'] == str(main)
    assert out['local_cli_version'] == 'catbus 0.3.0 (local)'
    assert 'ask the user' in out['hint'].lower() and 'npm i -g catbus-cli' in out['hint']


def test_installer_mode_ignores_a_path_cli(monkeypatch):
    """The shared detector applies the same source rule as the canvas backend: no PATH fallback."""
    from services.components import source
    from services.ingest import catbus_toolchain as toolchain

    monkeypatch.setattr(source, 'prefer_bundled', lambda: True)
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/catbus')
    monkeypatch.setattr(toolchain, 'local_checkout', lambda entry='': ('', ''))

    found = toolchain.direct_cli_candidates('/installer/dist/integrations/crawler-workflow/cli.js')

    assert found['cli'] == '', 'a machine catbus on PATH is not the installer’s copy'
    assert found['local_cli'] == ''


def test_source_mode_reports_a_path_cli(monkeypatch):
    from services.components import source
    from services.ingest import catbus_toolchain as toolchain

    monkeypatch.setattr(source, 'prefer_bundled', lambda: False)
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/catbus')
    monkeypatch.setattr(toolchain, 'local_checkout', lambda entry='': ('', ''))

    found = toolchain.direct_cli_candidates('/some/adapter/cli.js')

    assert found['cli'] == '/usr/bin/catbus'


def test_catbus_is_a_registered_read_only_tool(monkeypatch):
    from ai import tools

    spec = tools.TOOLS['catbus_status']
    assert spec.permission.startswith('read:'), 'detection may not need an approval'
    assert spec.handler is tools.tool_catbus_status
    assert 'catbus_status' in [item['name'] for item in tools.schemas(allow_files=False)]

    from ai.workspace import ALLOWED_COMMANDS

    assert 'catbus' in ALLOWED_COMMANDS, 'the direct path needs the CLI in the command allowlist'


def test_the_catbus_skill_asks_before_it_acts():
    from ai import skills

    skill = skills.BUILTIN['catbus']
    assert skill.local_only is True
    assert 'catbus_status' in skill.tools and 'capabilities' in skill.tools
    assert 'run_cmd' in skill.tools and 'workspace_import' in skill.tools
    assert 'ask_user_question' not in skill.tools, 'control tools are always available, never allowlisted'
    assert 'ask_user_question' in skill.prompt
    assert '建画布节点' in skill.prompt and 'AI 直接调 catbus 指令运行' in skill.prompt
    assert 'catbus_status' in skill.prompt and 'never install' in skill.prompt
    assert '用本地已有的' in skill.prompt and '下载安装全局 catbus CLI' in skill.prompt
    assert 'ask_user_question' in skill.prompt, 'local build vs install is the user’s choice'

    crawl = skills.BUILTIN['crawl']
    assert 'ask_user_question' in crawl.prompt, 'a general crawl request asks the same routing question'
    assert 'catbus_status' in crawl.tools


def test_cloud_refuses_the_catbus_skill_by_name(monkeypatch):
    from ai import skills
    from ai.providers import get_provider
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    allowed, reason = skills.availability(skills.BUILTIN['catbus'], get_provider('deepseek'))
    assert allowed is False
    assert reason.startswith('ai.skillLocalOnly')
    assert skills.reason_text(reason)[0] == 'ai.skillLocalOnly'


def test_route_sends_catbus_mentions_to_its_skill():
    from ai import skills

    assert skills.route('帮我用 catbus 采集小红书') == 'catbus'
    assert skills.route('本机装了 catbus 吗') == 'catbus'
    assert skills.route('我想采集微博数据') == 'crawl'


def test_the_authoritative_catbus_docs_are_searchable():
    from ai.context import docs_search

    hits = docs_search('catbus auth login 登录', limit=5)
    assert hits, 'the copied skill files must be reachable by docs_search'
    assert any('catbus' in hit['title'].lower() for hit in hits)
