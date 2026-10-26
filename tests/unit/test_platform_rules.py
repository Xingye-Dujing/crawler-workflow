"""The three-platform rules AGENTS.md states, as executable contracts.

The only honest way to prove a platform branch is to ask that branch for its answer, so every case here
passes a ``system`` argument instead of monkeypatching the running one: the Linux and macOS answers get
checked on the Windows box that wrote them. What this suite CANNOT do is start the app on Linux — this
machine has no Linux runtime (no docker, no WSL, by the user's decision), so a real Linux/macOS boot stays
an explicitly unverified surface, named as such in ``docs/agent_practices.md``.
"""

import io
import os
import re
from pathlib import Path

import pytest

import crawl_capabilities as capabilities
from crawl_capabilities import REQUIREMENTS, machine_requirements, mode_blocker, requirement_met
from engine.workflow import WorkflowEngine
from i18n import MESSAGES
from services import latex_charts, visualizer
from services.latex_compile import XELATEX_PATHS
from utils import machine_deps, procs
from utils.helpers import MAX_FILENAME_BYTES, sanitize_filename

pytestmark = pytest.mark.unit

#: Captured at import, before the suite-wide ``machine_has_a_browser`` pin replaces the attribute.
REAL_FIND_CHROME = machine_deps.find_chrome

BACKEND = Path(__file__).resolve().parents[2] / 'backend'

#: Where a Windows spelling is a legitimate fact about Windows: the per-OS tables, the process reaper
# (whose Windows branch IS ``taskkill``), the harvest stack that only exists on a desktop, ``i18n`` (a
# refusal that tells the user to point at ``chrome.exe`` is naming a file they must see, not building a
# path), and the download blocklist that refuses to hand out an executable.
WINDOWS_TABLES = {
    Path('utils/machine_deps.py'),
    Path('utils/procs.py'),
    Path('services/latex_compile.py'),
    Path('crawlers/hongguo_harvest.py'),
    Path('i18n.py'),
    Path('services/export_browser.py'),
}

#: Only the artifacts that actually break a Linux or macOS install. A bare drive letter is not in here:
# in source text ``KEEP:\s`` and ``C:\Program`` are the same three characters, and a scan that cries at
# every regex is a scan somebody switches off. Docstring prose is skipped by :func:`_code_lines`.
_WINDOWS_ARTIFACT = re.compile(
    r'Program Files|LOCALAPPDATA|PROGRAMFILES|taskkill|ctypes\.windll|winreg|os\.startfile|msvcrt|\.exe["\']'
)

_DOC_TRIPLE = re.compile('"""')


def _code_lines(text: str) -> list[str]:
    """The lines of ``text`` that are not a comment and not inside a docstring, with trailing comments cut.

    Counting the module's own ``_DOC_TRIPLE`` per line and toggling is the whole trick; a line holding two
    of them (a one-line docstring) leaves the state where it found it, which is what a docstring on one
    line means. A trailing hash-comment is prose about the code — an inline note saying 「never a global
    taskkill」 must not read as a call to it.
    """
    lines = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        fences = len(_DOC_TRIPLE.findall(line))
        if fences % 2:
            inside = not inside
            continue
        if inside:
            continue
        code = line.split('#', 1)[0].strip() if not line.startswith('#') else ''
        if code:
            lines.append(code)
    return lines


def _backend_source(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding='utf-8', errors='replace')


class TestTheRuleHasTeeth:
    """A rule nobody checks is a comment that everyone stops reading."""

    def test_no_product_module_hardcodes_windows_outside_the_platform_tables(self):
        offenders = []
        for path in sorted(BACKEND.rglob('*.py')):
            relative = path.relative_to(BACKEND)
            if path.name.startswith('test_') or relative in WINDOWS_TABLES or '__pycache__' in path.parts:
                continue
            for line in _code_lines(path.read_text(encoding='utf-8', errors='replace')):
                if _WINDOWS_ARTIFACT.search(line):
                    offenders.append(f'{relative}:{line[:90]}')
        assert offenders == [], 'Windows-only code outside the per-OS tables:\n' + '\n'.join(offenders)

    def test_the_scan_sees_a_windows_call_and_ignores_prose_about_one(self):
        # A guard that cannot fire is worse than no guard: it only claims the rule is checked.
        sample = 'x = 1\n"""\nUsed to run taskkill /F /IM chromedriver.exe here.\n"""\ny = ctypes.windll\n'
        assert 'Used to run taskkill' not in _code_lines(sample)
        assert any('ctypes.windll' in line for line in _code_lines(sample))

    def test_each_exempted_file_actually_holds_a_windows_artifact(self):
        # An exemption that exempts nothing is how an allowlist rots into a lie.
        for relative in WINDOWS_TABLES:
            path = BACKEND / relative
            assert path.is_file(), path
            assert _WINDOWS_ARTIFACT.search(path.read_text(encoding='utf-8')), relative


class TestThePlatformTablesAreComplete:
    def test_every_remedy_key_exists_in_both_languages_and_needs_no_arguments(self):
        for prefix in machine_deps.REMEDY_PREFIXES:
            for system in machine_deps.REMEDY_PLATFORMS:
                key = machine_deps.remedy_key(prefix, system)
                for lang, table in MESSAGES.items():
                    text = table.get(key)
                    assert text and text != key, f'{lang} has no remedy for {key}'
                    assert '{' not in text, f'{key} in {lang} carries an unfilled slot'

    def test_the_three_platforms_are_told_to_install_three_different_things(self):
        answers = {system: machine_deps.remedy('deps.xelatex', system) for system in machine_deps.REMEDY_PLATFORMS}
        assert len(set(answers.values())) == 3, answers
        assert 'MiKTeX' in answers['win32']
        assert 'texlive-xetex' in answers['linux']
        assert 'MacTeX' in answers['darwin']

    def test_every_table_is_indexed_by_exactly_the_three_platforms(self):
        for name, table in (
            ('CHROME_PATHS', machine_deps.CHROME_PATHS),
            ('CHROME_PATH_NAMES', machine_deps.CHROME_PATH_NAMES),
            ('XELATEX_PATHS', XELATEX_PATHS),
            ('CTEX_FONTSET', latex_charts.CTEX_FONTSET),
            ('CJK_FAMILY', latex_charts.CJK_FAMILY),
            ('REQUIREMENT_LABELS', capabilities.REQUIREMENT_LABELS),
        ):
            assert set(table) == set(machine_deps.REMEDY_PLATFORMS) or name == 'REQUIREMENT_LABELS', name
        assert set(capabilities.REQUIREMENT_LABELS) == set(REQUIREMENTS)

    def test_platform_name_normalizes_the_spellings_python_actually_reports(self):
        assert machine_deps.platform_name('linux5') == 'linux'
        assert machine_deps.platform_name('darwin23.4') == 'darwin'
        assert machine_deps.platform_name('cygwin') == 'win32'
        assert machine_deps.is_windows('darwin') is False
        assert machine_deps.is_windows('win32') is True


class TestChromeDiscoveryPerPlatform:
    @pytest.fixture(autouse=True)
    def _real_probe(self, monkeypatch):
        # ``tests/conftest.py`` pins ``find_chrome`` so no crawler case depends on this box's browsers.
        # These cases ARE about that probe, so they put the real one back.
        monkeypatch.setattr(machine_deps, 'find_chrome', REAL_FIND_CHROME)

    def test_linux_offers_the_paths_a_server_actually_has(self):
        found = machine_deps.chrome_candidate_paths('linux', {'PATH': '/usr/bin:/snap/bin'})
        assert '/usr/bin/google-chrome' in found
        assert '/snap/bin/chromium' in found, 'a snap install is Ubuntu packaging'
        assert not any('chrome.exe' in path for path in found)

    def test_macos_offers_the_app_bundle_in_posix_shape_even_asked_from_windows(self):
        found = machine_deps.chrome_candidate_paths('darwin', {'PATH': '/usr/bin', 'HOME': '/Users/someone'})
        assert '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' in found
        assert '/Users/someone/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' in found
        assert all('\\' not in path for path in found), 'a POSIX answer must not borrow the host separators'

    def test_windows_still_builds_the_windows_spelling_from_its_roots(self):
        found = machine_deps.chrome_candidate_paths('win32', {'PROGRAMFILES': 'C:\\Program Files', 'PATH': ''})
        assert 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' in found

    def test_an_explicit_variable_is_answered_before_any_root(self):
        found = machine_deps.chrome_candidate_paths('linux', {'CHROME_BIN': '/opt/chrome', 'PATH': '/usr/bin'})
        assert found[0] == '/opt/chrome', 'the image exports CHROME_BIN for a reason'

    def test_only_a_file_that_exists_is_an_answer(self, tmp_path):
        real = tmp_path / 'chromium'
        real.write_bytes(b'MZ')
        found = machine_deps.chrome_candidates({'CHROME_BIN': str(real), 'PATH': str(tmp_path)}, 'linux')
        assert found[0] == str(real)
        assert machine_deps.chrome_candidates({'CHROME_BIN': str(tmp_path / 'absent'), 'PATH': ''}, 'linux') == []

    @pytest.mark.skipif(os.name == 'nt', reason='the executable bit is a POSIX fact')
    def test_a_file_that_is_not_executable_is_refused_rather_than_launched(self, tmp_path):
        real = tmp_path / 'chromium'
        real.write_bytes(b'MZ')
        os.chmod(real, 0o600)
        assert machine_deps.chrome_candidates({'CHROME_BIN': str(real), 'PATH': ''}, 'linux') == []

    def test_a_typo_names_itself_on_every_platform(self, tmp_path):
        real = tmp_path / 'chrome'
        real.write_bytes(b'MZ')
        assert machine_deps.find_chrome('', {'CHROME_BIN': str(real), 'PATH': ''}, 'linux') == str(real)
        assert machine_deps.find_chrome(str(tmp_path / 'nope'), {'PATH': ''}, 'linux') == ''
        assert machine_deps.find_chrome(str(tmp_path / 'nope'), {'PATH': ''}, 'darwin') == ''


class TestNodeAndCatbusDiscoveryPerPlatform:
    """The second crawl backend is two machine-level facts, so it is looked up like Chrome is.

    A cloud server installs Node from a distro package and CatBus with npm into a prefix nobody
    exports; the desktop build ships neither. Both answers have to come from one table per OS, or
    「没有 CatBus」 and 「CatBus 坏了」 become the same message.
    """

    def test_linux_offers_the_runtimes_a_server_actually_has(self):
        found = machine_deps.node_candidate_paths('linux', {'PATH': '/usr/bin:/usr/local/bin'})
        assert '/usr/bin/node' in found
        assert '/usr/local/bin/node' in found, 'a nodesource install lands here'
        assert not any('node.exe' in path for path in found), 'a Linux answer has no Windows suffix'

    def test_macos_and_linux_answers_stay_in_the_targets_separators(self):
        for system in ('linux', 'darwin'):
            found = machine_deps.node_candidate_paths(system, {'PATH': '/usr/local/bin'})
            assert all('\\' not in path for path in found), f'{system} must not borrow the host separators'

    def test_windows_still_builds_the_windows_spelling_from_its_roots(self):
        found = machine_deps.node_candidate_paths('win32', {'PROGRAMFILES': 'C:\\Program Files', 'PATH': ''})
        assert 'C:\\Program Files\\nodejs\\node.exe' in found

    def test_an_explicit_node_variable_is_answered_before_any_root(self):
        found = machine_deps.node_candidate_paths('linux', {'NODE_BIN': '/opt/nvm/v24/bin/node', 'PATH': '/usr/bin'})
        assert found[0] == '/opt/nvm/v24/bin/node', 'an nvm install is not findable any other way'

    def test_linux_offers_the_npm_roots_a_cloud_box_installs_into(self):
        env = {'PATH': '/opt/node/bin:/usr/bin', 'HOME': '/srv/cixi'}
        found = machine_deps.catbus_candidate_paths('linux', env)
        tail = f'{machine_deps.CATBUS_PACKAGE}/' + '/'.join(machine_deps.CATBUS_ENTRY)
        assert f'/usr/local/lib/node_modules/{tail}' in found, 'the npm default prefix'
        assert f'/srv/cixi/.npm-global/lib/node_modules/{tail}' in found, (
            'a prefix-less npm install is the unprivileged answer'
        )
        assert f'/opt/node/lib/node_modules/{tail}' in found, 'a PATH entry /opt/node/bin points one level up'
        assert not any('\\' in path for path in found)

    def test_a_source_checkout_is_named_by_its_root_not_its_file(self):
        found = machine_deps.catbus_candidate_paths('linux', {'CATBUS_HOME': '/srv/catbus', 'PATH': ''})
        assert '/srv/catbus/dist/integrations/crawler-workflow/cli.js' in found

    def test_macos_offers_the_homebrew_prefix_and_windows_the_appdata_one(self):
        mac = machine_deps.catbus_candidate_paths('darwin', {'PATH': '/opt/homebrew/bin'})
        assert '/opt/homebrew/lib/node_modules/catbus-cli/dist/integrations/crawler-workflow/cli.js' in mac
        assert all('\\' not in path for path in mac)
        win = machine_deps.catbus_candidate_paths('win32', {'APPDATA': 'C:\\Users\\l\\AppData\\Roaming', 'PATH': ''})
        assert 'C:\\Users\\l\\AppData\\Roaming\\npm\\node_modules\\catbus-cli\\dist' in '\\'.join(win)

    def test_only_a_file_that_exists_is_an_answer(self, tmp_path):
        real = tmp_path / 'cli.js'
        real.write_text('// catbus\n', encoding='utf-8')
        found = machine_deps.catbus_candidates({'CIXI_CATBUS_CLI': str(real), 'PATH': str(tmp_path)}, 'linux')
        assert found[0] == str(real)
        assert machine_deps.find_node('/nope/node', {'PATH': ''}, 'linux') == '', 'a typo names itself'
        assert machine_deps.find_catbus_cli('/nope/cli.js', {'PATH': ''}, 'darwin') == ''

    @pytest.mark.skipif(os.name == 'nt', reason='the executable bit is a POSIX fact')
    def test_an_entry_without_the_executable_bit_is_refused_rather_than_run(self, tmp_path):
        real = tmp_path / 'node'
        real.write_bytes(b'#!/bin/sh\n')
        os.chmod(real, 0o600)
        assert machine_deps.node_candidates({'NODE_BIN': str(real), 'PATH': ''}, 'linux') == []

    def test_a_script_entry_is_read_not_run(self, tmp_path):
        """npm and git both install ``cli.js`` as mode 644, and demanding ``+x`` made the second
        backend disappear on every POSIX box — silently, because 「no CatBus」 is a verdict, not an
        error. A file Node *reads* only has to be readable; the rule is about what the file is."""
        script = tmp_path / 'cli.js'
        script.write_text('// catbus\n', encoding='utf-8')
        os.chmod(script, 0o644)
        assert machine_deps.catbus_entry_usable(str(script))
        assert machine_deps.catbus_candidates({'CIXI_CATBUS_CLI': str(script), 'PATH': ''}, 'linux') == [str(script)]

    @pytest.mark.skipif(os.name == 'nt', reason='the executable bit is a POSIX fact')
    def test_a_wrapper_entry_still_has_to_be_runnable(self, tmp_path):
        """No script suffix means the bridge spawns it directly, so its mode really is the answer."""
        wrapper = tmp_path / 'catbus'
        wrapper.write_bytes(b'#!/bin/sh\n')
        os.chmod(wrapper, 0o644)
        assert machine_deps.find_catbus_cli(str(wrapper), {'PATH': ''}, 'linux') == ''

    def test_the_version_floors_are_catbus_engines_translated(self):
        assert machine_deps.node_version_supported('v24.21.0')
        assert machine_deps.node_version_supported('v26.0.0')
        assert machine_deps.node_version_supported('v31.0.0'), '>=26 is open-ended'
        assert machine_deps.node_version_supported('22.22.2')
        assert not machine_deps.node_version_supported('v22.22.1'), 'the floor is a patch level, not a major'
        assert not machine_deps.node_version_supported('v18.20.4'), 'Node 18 is outside the range'
        # ``^22.22.2 || ^24.15.0`` are major-bound: an even release between them is newer than the
        # first floor and supported by neither, and ``any(v >= floor)`` would wave it through.
        assert not machine_deps.node_version_supported('v23.11.0'), '23.x is in no caret range'
        assert not machine_deps.node_version_supported('v25.1.0'), '25.x is in no caret range'
        assert not machine_deps.node_version_supported('v24.14.9'), 'the 24 range starts at 24.15.0'
        assert not machine_deps.node_version_supported(''), 'an unreadable answer is not evidence of a new runtime'
        assert not machine_deps.node_version_supported('v24')


class TestTheMatplotlibFontStackHoldsEachOsNames:
    @pytest.fixture(autouse=True)
    def _fresh_caches(self):
        visualizer.cjk_font.cache_clear()
        visualizer._warn_missing_cjk_font.cache_clear()
        yield
        visualizer.cjk_font.cache_clear()
        visualizer._warn_missing_cjk_font.cache_clear()

    def test_the_names_a_linux_or_mac_install_registers_are_asked_for(self):
        for family in ('Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'PingFang SC', 'Source Han Sans SC'):
            assert family in visualizer.FONT_STACK, family

    def test_the_windows_names_stay_first_so_a_desktop_answer_does_not_move(self):
        assert visualizer.FONT_STACK[:2] == ['SimHei', 'Microsoft YaHei']

    def test_the_warning_offers_this_platforms_remedy(self, monkeypatch, caplog):
        class Manager:
            def findfont(self, family, fallback_to_default=True):
                raise ValueError('absent')

        monkeypatch.setattr('matplotlib.font_manager.fontManager', Manager())
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'linux')
        visualizer._pyplot()
        text = ' '.join(record.message for record in caplog.records)
        assert 'fonts-noto-cjk' in text, 'a Linux box must not be told to install a Windows font'


class TestThePaperFontSetFollowsTheMachine:
    def test_the_ctex_option_is_empty_on_windows_and_named_elsewhere(self):
        assert latex_charts.ctex_options('win32') == ''
        assert latex_charts.ctex_options('linux') == 'fontset=fandol'
        assert latex_charts.ctex_options('darwin') == 'fontset=macnew'

    def test_the_package_line_carries_the_option(self):
        assert latex_charts._packages('win32').splitlines()[0] == '\\usepackage{ctex}'
        assert latex_charts._packages('linux').splitlines()[0] == '\\usepackage[fontset=fandol]{ctex}'

    def test_windows_keeps_the_measured_fangsong_lines(self, monkeypatch):
        # 26/26 figures and tables compiled with exactly these three lines on MiKTeX (A19), so the Windows
        # branch is pinned rather than trusted to still say what it said.
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'win32')
        assert r'\setCJKmainfont[scale=0.95,AutoFakeBold=2.0]{FangSong}' in latex_charts.paper_preamble()

    def test_a_paper_asked_for_off_windows_names_no_font_that_is_not_there(self, monkeypatch):
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'linux')
        preamble = latex_charts.paper_preamble()
        code = '\n'.join(line for line in preamble.splitlines() if not line.startswith('%'))
        assert '\\setCJKmainfont' not in code, 'FangSong is not installed on a Linux TeX Live'
        assert '\\usepackage[fontset=fandol]{ctex}' in preamble
        assert '仿宋' in preamble, 'the source says what it did and why'

    def test_the_pasted_hint_says_what_this_machine_used(self, monkeypatch):
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'darwin')
        head = latex_charts.LatexChartService._standalone_head('图', 'bar', 't', 'c')
        assert 'fontset=macnew' in head
        assert 'Songti SC' in head


class TestTheDeployFilesSayWhatTheCodeReads:
    """A deploy knob nothing reads is worse than no knob: the image looks configured and is not."""

    #: Variables the INTERPRETER or the OS reads, so no line of this program names them: `PYTHONUTF8`
    # decides the default stream encoding and `LANG` decides that and the locale's collation. A check that
    # called these "unread" would be a check that punishes the correct fix for the ASCII-console bug.
    INTERPRETER_VARS = ('LANG', 'PYTHONUTF8', 'PATH', 'HOME')

    def test_every_environment_variable_the_image_exports_is_one_the_code_asks_for(self):
        root = BACKEND.parent
        image = (root / 'Dockerfile').read_text(encoding='utf-8')
        declared = set(re.findall(r'^ENV\s+([A-Z_][A-Z0-9_]*)', image, re.MULTILINE))
        sources = '\n'.join(
            path.read_text(encoding='utf-8', errors='replace')
            for path in [BACKEND / 'config.py', BACKEND / 'app.py', BACKEND / 'utils' / 'machine_deps.py']
        )
        unread = sorted(name for name in declared if f"'{name}'" not in sources and name not in self.INTERPRETER_VARS)
        assert unread == [], f'the image exports variables no code reads: {unread}'
        assert 'CIXI_DRIVER_PATH' in declared, 'the driver path knob is named CIXI_DRIVER_PATH, not CHROMEDRIVER_PATH'

    def test_the_windows_only_optional_packages_are_marked(self):
        # ``uiautomation`` is a comtypes-based Windows sdist: unmarked, `pip install -r
        # requirements-optional.txt` was a Windows-only command on a project that deploys to Linux.
        text = (BACKEND.parent / 'requirements-optional.txt').read_text(encoding='utf-8')
        for name in ('mitmproxy', 'uiautomation'):
            line = next((row for row in text.splitlines() if row.strip().startswith(name)), '')
            assert 'sys_platform == "win32"' in line, f'{name} must be Windows-marked: {line}'


class TestAFileNameLimitIsBytesNotCharacters:
    def test_a_chinese_name_is_cut_by_its_utf8_length(self):
        # 100 Chinese characters are ~300 UTF-8 bytes: inside a Windows character cap, over ext4's NAME_MAX.
        safe = sanitize_filename('数' * 300)
        assert len(safe.encode('utf-8')) <= MAX_FILENAME_BYTES
        assert safe, 'a cap that empties the name is not a cap'

    def test_the_extension_survives_a_byte_cut(self):
        safe = sanitize_filename('标' * 200 + '.csv')
        assert safe.endswith('.csv')
        assert len(safe.encode('utf-8')) <= MAX_FILENAME_BYTES

    def test_an_ascii_name_under_the_character_cap_is_untouched(self):
        assert sanitize_filename('report.csv') == 'report.csv'

    def test_a_cut_never_splits_a_character_in_half(self):
        sanitize_filename('中' * 300).encode('utf-8').decode('utf-8')

    def test_the_byte_cap_binds_before_the_character_cap_for_chinese(self):
        # The character cap alone would let a 100-glyph Chinese name through, and 300 bytes is over NAME_MAX.
        assert len(('数' * 100).encode('utf-8')) > MAX_FILENAME_BYTES


class TestReapingABrowserWorksWhereTaskkillDoesNot:
    def test_the_windows_answer_is_the_tree_kill_it_was(self):
        assert procs.reap_command(4321, 'win32') == ['taskkill', '/F', '/T', '/PID', '4321']

    def test_posix_asks_for_no_taskkill(self):
        assert procs.reap_command(4321, 'linux') == []

    def test_a_spawned_helper_gets_no_console_window_only_where_there_are_windows(self):
        # The CatBus backend starts Node once per comment link. ``CREATE_NO_WINDOW`` exists only in
        # Windows' subprocess module, so asking for it unconditionally is a Linux TypeError — and
        # asking never is a Windows user watching a black window flash per link.
        assert procs.popen_kwargs('win32') == {'creationflags': 0x08000000}
        assert procs.popen_kwargs('linux') == {}
        assert procs.popen_kwargs('darwin') == {}

    def test_windows_stops_the_whole_tree_in_one_command(self, monkeypatch):
        calls = []

        class Result:
            returncode = 0
            stdout = b''
            stderr = b''

        def fake_run(command, **_kwargs):
            calls.append(command)
            return Result()

        monkeypatch.setattr(procs.subprocess, 'run', fake_run)
        assert procs.reap_process(4321, 'win32') == (True, '')
        assert calls == [['taskkill', '/F', '/T', '/PID', '4321']]

    def test_linux_children_go_before_the_driver_that_spawned_them(self, tmp_path, monkeypatch):
        root = tmp_path / 'proc'
        for pid, ppid in ((4321, 1), (5001, 4321), (5002, 4321), (9999, 7)):
            directory = root / str(pid)
            directory.mkdir(parents=True)
            (directory / 'stat').write_text(f'{pid} (chrome) S {ppid} 0 0', encoding='utf-8')
        killed = []
        monkeypatch.setattr(procs.os, 'kill', lambda pid, _signal: killed.append(pid))
        stopped, reason = procs.reap_process(4321, 'linux', str(root))
        assert stopped and reason == ''
        assert killed == [5001, 5002, 4321], 'the parent must not outlive the browsers it started'

    def test_a_process_the_kernel_does_not_know_is_already_stopped(self, monkeypatch):
        def raise_lookup(_pid, _signal):
            raise ProcessLookupError

        monkeypatch.setattr(procs.os, 'kill', raise_lookup)
        assert procs.reap_process(4321, 'linux', '/definitely/nowhere') == (True, '')

    def test_a_refused_kill_is_reported_not_swallowed(self, monkeypatch):
        def refuse(_pid, _signal):
            raise PermissionError('Operation not permitted')

        monkeypatch.setattr(procs.os, 'kill', refuse)
        stopped, reason = procs.reap_process(4321, 'linux', '/definitely/nowhere')
        assert stopped is False
        assert 'permitted' in reason and '4321' in reason

    def test_the_close_path_marks_the_session_dead_even_when_the_reap_refused(self):
        # The promise is about the worker's session, not about the process: leaving a live driver in place
        # is what made the next crawl of that platform wait out the profile lock.
        block = _backend_source('app.py').split('def _close_login_browser', 1)[1].split('\ndef ', 1)[0]
        assert 'procs.reap_process(' in block
        assert 'crawler.driver = DeadDriver()' in block
        assert 'suppress(Exception):\n            subprocess.run' not in block


class TestAModeThatNeedsWindowsIsRefusedBeforeItCostsARun:
    def test_every_requirement_token_has_words_in_both_languages(self):
        for token in REQUIREMENTS:
            key = capabilities.REQUIREMENT_LABELS[token]
            for lang, table in MESSAGES.items():
                assert table.get(key) and table[key] != key, (token, lang)

    def test_the_front_end_holds_the_same_token_list_as_the_server(self):
        # A computed key is only safe when the WHOLE universe of values was asked about (the nodeType
        # lesson): a token the server can send with no word in app.js prints an empty reason.
        root = BACKEND / 'static' / 'js'
        app_words = (root / 'app.js').read_text(encoding='utf-8')
        table = (root / 'workflow.js').read_text(encoding='utf-8')
        listed = set(re.findall(r"(\w+):\s*'cap\.requires[A-Za-z]+'", table))
        assert listed == set(REQUIREMENTS), listed
        for token in REQUIREMENTS:
            key = capabilities.REQUIREMENT_LABELS[token]
            assert app_words.count(f"'{key}'") >= 2, f'{key} needs a word in both catalogues'

    def test_the_harvest_mode_carries_the_requirement_and_the_boards_do_not(self):
        hongguo = next(capability for capability in capabilities.CAPABILITIES if capability.platform == 'hongguo')
        by_key = {mode.key: mode for mode in hongguo.modes}
        assert by_key['comments'].requires == 'windows_desktop'
        assert [key for key, mode in by_key.items() if not mode.requires], 'the boards run anywhere'

    def test_a_windows_desktop_runs_it_and_everything_else_refuses(self):
        mode = _harvest_mode()
        assert mode_blocker(mode, 'win32', cloud=False) == ''
        for system, cloud in (('linux', False), ('darwin', False), ('win32', True)):
            blocked = mode_blocker(mode, system, cloud)
            assert blocked, (system, cloud)
            assert 'Windows' in MESSAGES['en'][blocked]

    def test_the_machine_answer_agrees_with_the_per_mode_verdict(self):
        assert machine_requirements('linux', cloud=False)['windows_desktop'] is False
        assert requirement_met('windows_desktop', 'win32', cloud=True) is False
        assert requirement_met('an_unknown_token', 'linux', cloud=True) is True, 'never hide on a guess'

    def test_the_capabilities_payload_carries_the_requirement(self):
        harvest = [
            capabilities._mode_as_dict(mode)
            for capability in capabilities.CAPABILITIES
            for mode in capability.modes
            if mode.requires
        ]
        assert harvest and harvest[0]['requires'] == 'windows_desktop'
        assert all('requires' in m for m in capabilities.as_dict()['platforms'][0]['modes'])

    def test_the_backend_validation_refuses_the_mode_on_a_linux_server(self, monkeypatch):
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'linux')
        canvas = {
            'nodes': [
                {
                    'id': 'node-1',
                    'type': 'source',
                    'platform': 'hongguo',
                    'params': {'collect': 'comments', 'urls': 'https://hongguoduanju.com/detail?series_id=1'},
                },
                {'id': 'node-2', 'type': 'output', 'params': {}},
            ],
            'connections': [{'from': 'node-1', 'to': 'node-2'}],
        }
        messages = WorkflowEngine(canvas).validate()
        about_node = [message for message in messages if 'node-1' in message]
        assert len(about_node) == 1, about_node
        assert 'Windows' in about_node[0] or '这台机器' in about_node[0], about_node

    def test_the_same_canvas_on_a_windows_box_is_not_refused_for_the_machine(self, monkeypatch):
        monkeypatch.setattr(machine_deps, 'platform_name', lambda system=None: 'win32')
        canvas = {
            'nodes': [
                {
                    'id': 'node-1',
                    'type': 'source',
                    'platform': 'hongguo',
                    'params': {'collect': 'comments', 'urls': 'https://hongguoduanju.com/detail?series_id=1'},
                },
                {'id': 'node-2', 'type': 'output', 'params': {}},
            ],
            'connections': [{'from': 'node-1', 'to': 'node-2'}],
        }
        assert not [m for m in WorkflowEngine(canvas).validate() if 'Windows' in m or '这台机器' in m]


def _harvest_mode():
    for capability in capabilities.CAPABILITIES:
        for mode in capability.modes:
            if mode.requires == 'windows_desktop':
                return mode
    raise AssertionError('no mode carries the windows_desktop requirement')


class TestAConsoleThatCannotWriteChineseIsFixedAtStartup:
    @staticmethod
    def _pair(encoding: str):
        buffer = io.BytesIO()
        # ``newline='\n'`` because the thing under test is the ENCODING: left at its default a Windows host
        # turns every ``\n`` into ``\r\n`` and the assertion ends up describing the box it ran on.
        return buffer, io.TextIOWrapper(buffer, encoding=encoding, newline='\n')

    def test_a_stream_that_holds_han_characters_keeps_its_encoding(self):
        buffer, stream = self._pair('utf-8')
        assert machine_deps.can_write_chinese(stream) is True
        assert machine_deps.pin_console(stream) == ''
        stream.write('汉字 ok\n')
        stream.flush()
        assert '汉字' in buffer.getvalue().decode('utf-8')

    def test_an_ascii_console_is_moved_to_utf8_and_says_what_it_was(self):
        buffer, stream = self._pair('ascii')
        assert machine_deps.can_write_chinese(stream) is False
        assert machine_deps.pin_console(stream) == 'ascii'
        stream.write('汉字\n')
        stream.flush()
        assert buffer.getvalue().decode('utf-8') == '汉字\n'

    def test_an_unmappable_character_never_costs_the_whole_line(self):
        buffer, stream = self._pair('cp437')
        machine_deps.pin_console(stream)
        stream.write('问题 \ud800\n')  # a lone surrogate: nothing in the tree can encode it
        stream.flush()
        written = buffer.getvalue().decode('utf-8', 'replace')
        assert '问题' in written, 'the rest of the line still reached the console'

    def test_a_stream_naming_an_unknown_codec_is_not_credited_with_writing_han(self):
        # ``TextIOWrapper`` refuses a bad codec at construction, so the only way this branch is reached is
        # a foreign stream object that REPORTS a name no codec answers to — a tee, a captured pipe, a
        # test double. Those are exactly the objects that decide whether the app's console line survives.
        class Foreign:
            encoding = 'not-a-codec'

        assert machine_deps.can_write_chinese(Foreign()) is False

    def test_a_stream_without_reconfigure_is_left_alone(self):
        class Plain:
            encoding = 'ascii'

            def write(self, _text):
                raise UnicodeEncodeError('ascii', 'x', 0, 1, 'nope')

        assert machine_deps.pin_console(Plain(), 'stdout') == ''

    def test_the_pinning_runs_at_import_not_per_request(self):
        source = _backend_source('app.py')
        block = source.split('def pin_console_streams', 1)[1].split('\ndef ', 1)[0]
        assert 'machine_deps.pin_console(' in block
        assert 'pin_console_streams()' in source.split('def pin_console_streams', 1)[1]
