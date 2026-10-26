"""What the app says when a machine-level dependency is not there.

These are the answers a user can act on: which Chrome path is wrong, which driver to fetch, which
MiKTeX package is missing, which font to install, where to unpack the model pack, and what to put in
「设置 → Ollama 地址」. Each case exists because the alternative was worse — an exception from a child
process, a figure full of boxes, or a PDF that simply never appeared.
"""

import logging
import sys
from pathlib import Path

import pytest

import services.latex_compile as latex_compile
import services.visualizer as visualizer
from analyzers.sentiment import BertClassifier
from utils import machine_deps

pytestmark = pytest.mark.unit

#: Captured at import, before the suite-wide ``machine_has_a_browser`` pin replaces the attribute.
#: These tests are about the probe itself, so they answer for it.
REAL_FIND_CHROME = machine_deps.find_chrome


class TestTheMachineProbes:
    @pytest.fixture(autouse=True)
    def _real_probe(self, monkeypatch):
        monkeypatch.setattr(machine_deps, 'find_chrome', REAL_FIND_CHROME)

    def test_an_explicit_browser_path_is_the_answer_or_nothing(self, tmp_path):
        real = tmp_path / 'chrome.exe'
        real.write_bytes(b'MZ')
        assert machine_deps.find_chrome(str(real)) == str(real)
        # A typo must not be papered over by a Chrome the user never chose: a copied profile is a
        # second device to a site's risk control, so which browser ran is the user's decision.
        assert machine_deps.find_chrome(str(tmp_path / 'typo.exe')) == ''

    def test_candidates_are_read_from_the_environment_and_must_exist(self, tmp_path):
        chrome = tmp_path / 'chrome.exe'
        env = {'PROGRAMFILES': str(tmp_path), 'CHROME_PATH': str(chrome), 'CHROME_BIN': ''}
        assert machine_deps.chrome_candidates(env) == [], 'no candidate exists on disk yet'
        chrome.write_bytes(b'MZ')
        found = machine_deps.chrome_candidates(env)
        assert found == [str(chrome)], 'the env override answers, the install root does not exist here'

    def test_a_configured_ollama_address_decides_the_port(self):
        # The launcher used to probe 127.0.0.1:11434 whatever the user had set, so a daemon on
        # another machine was reported as missing one line before the app answered from it.
        assert machine_deps.ollama_endpoint('http://192.168.1.9:11435') == ('192.168.1.9', 11435)
        assert machine_deps.ollama_endpoint('localhost') == ('localhost', 11434)
        assert machine_deps.ollama_endpoint('https://gpu.example') == ('gpu.example', 443)
        assert machine_deps.ollama_endpoint('') == ('localhost', 11434)

    def test_the_reachability_probe_answers_false_instead_of_raising(self, monkeypatch):
        def explode(_address, timeout=None):
            raise OSError('refused')

        monkeypatch.setattr(machine_deps.socket, 'create_connection', explode)
        assert machine_deps.ollama_reachable('http://127.0.0.1:1') is False

    def test_the_reachability_probe_answers_true_for_an_open_port(self, monkeypatch):
        class _Connection:
            """A socket stand-in: the probe closes what it opened, so it has to be a context manager."""

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        monkeypatch.setattr(machine_deps.socket, 'create_connection', lambda _address, timeout=None: _Connection())
        assert machine_deps.ollama_reachable('http://127.0.0.1:11434') is True

    def test_frozen_is_read_from_the_running_bundle_flag(self, monkeypatch):
        monkeypatch.delattr(sys, 'frozen', raising=False)
        assert machine_deps.is_frozen() is False
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        assert machine_deps.is_frozen() is True


class TestTheChineseFontAnswer:
    """A Matplotlib PNG with boxes instead of Chinese is a figure that gets pasted into a paper."""

    @pytest.fixture(autouse=True)
    def _fresh_font_answer(self):
        visualizer.cjk_font.cache_clear()
        visualizer._warn_missing_cjk_font.cache_clear()
        yield
        visualizer.cjk_font.cache_clear()
        visualizer._warn_missing_cjk_font.cache_clear()

    def test_the_stack_we_set_is_the_stack_we_check(self):
        # A warning about "the font stack" means nothing if the list it names is not the list the
        # figures are drawn with; one constant feeds both.
        plt = visualizer._pyplot()
        assert plt.rcParams['font.sans-serif'] == list(visualizer.FONT_STACK)
        assert [f for f in visualizer.FONT_STACK if f not in visualizer._NO_CHINESE] == visualizer._CJK_CANDIDATES

    def test_a_resolvable_family_is_the_answer(self, monkeypatch):
        class Manager:
            def findfont(self, family, fallback_to_default=True):
                if family == 'Microsoft YaHei':
                    return 'C:/Windows/Fonts/msyh.ttc'
                raise ValueError(f'no {family}')

        monkeypatch.setattr('matplotlib.font_manager.fontManager', Manager())
        assert visualizer.cjk_font() == 'Microsoft YaHei'

    def test_no_cjk_family_means_empty_and_exactly_one_printed_line(self, monkeypatch, caplog):
        class Manager:
            def findfont(self, family, fallback_to_default=True):
                raise ValueError(f'no {family}')

        monkeypatch.setattr('matplotlib.font_manager.fontManager', Manager())
        with caplog.at_level(logging.WARNING, logger='services.visualizer'):
            visualizer._pyplot()
            visualizer._pyplot()  # thirty figures in one canvas must say it once
        assert visualizer.cjk_font() == ''
        said = [record.message for record in caplog.records if record.levelno == logging.WARNING]
        assert len(said) == 1, said

    def test_the_warning_names_the_families_it_asked_for(self, monkeypatch, caplog):
        class Manager:
            def findfont(self, family, fallback_to_default=True):
                raise ValueError('absent')

        monkeypatch.setattr('matplotlib.font_manager.fontManager', Manager())
        with caplog.at_level(logging.WARNING, logger='services.visualizer'):
            visualizer._pyplot()
        text = ' '.join(record.message for record in caplog.records)
        for family in visualizer._CJK_CANDIDATES:
            assert family in text


class TestWhatALaTeXRefusalSays:
    def test_a_missing_package_is_named_as_a_package(self):
        message = latex_compile.explain_failure("! LaTeX Error: File `ctex.sty' not found.", b'')
        assert 'ctex' in message
        assert 'MiKTeX' in message

    def test_a_missing_font_is_named_as_a_font(self):
        log = '! Package fontspec Error: The font "FangSong" cannot be found.'
        message = latex_compile.explain_failure(log, b'')
        assert 'FangSong' in message
        assert '字体' in message or 'font' in message

    def test_anything_else_quotes_the_log_line_xelatex_wrote(self):
        # batchmode leaves stderr almost empty: the log is where the reason actually is.
        message = latex_compile.explain_failure('! Undefined control sequence.\nl.42 \\badmacro', b'')
        assert '! Undefined control sequence.' in message

    def test_a_compile_that_never_started_falls_back_to_stderr(self):
        message = latex_compile.explain_failure('', b'xelatex: security risk: running with elevated privileges')
        assert 'elevated privileges' in message

    def test_the_log_is_read_before_the_working_directory_goes_away(self):
        source = Path(latex_compile.__file__).read_text(encoding='utf-8')
        branch = source.split('if result.returncode != 0 or not os.path.isfile(produced):')[1]
        assert branch.index('_read_log(work)') < branch.index('shutil.rmtree(work'), (
            'the log has to be read while it still exists'
        )


class TestTheModelPackAnswer:
    """The desktop build's BERT models live in a separate archive the user unpacks."""

    def _refuse(self, monkeypatch, frozen: bool, tmp_path) -> str:
        monkeypatch.setattr(machine_deps, 'is_frozen', lambda: frozen)
        # Two levels deep, like the real layout: the registry holds ``bert_models/<name>``, and the
        # case this refusal is about is that ``bert_models`` itself was never unpacked.
        missing = tmp_path / 'bert_models' / 'bert_absent_onnx_fp16'
        with pytest.raises(ValueError) as caught:
            BertClassifier(str(missing), runtime='onnx')
        return str(caught.value)

    def test_the_desktop_build_points_at_the_pack_and_its_folder(self, monkeypatch, tmp_path):
        message = self._refuse(monkeypatch, True, tmp_path)
        assert 'bert_models' in message
        assert 'CaiXiHui-bert-models-win64.zip' in message
        assert 'bert_absent_onnx_fp16' in message, 'the name the registry holds must appear'

    def test_the_source_build_points_at_the_export_script(self, monkeypatch, tmp_path):
        message = self._refuse(monkeypatch, False, tmp_path)
        assert 'export_onnx_bert.py' in message
        assert 'CaiXiHui-bert-models-win64.zip' not in message, 'an unpack step nobody needs is noise'

    def test_a_folder_that_exists_but_holds_no_graph_still_says_so(self, monkeypatch, tmp_path):
        """A half-copied pack is a different fact from a missing one, and gets its own sentence."""
        monkeypatch.setattr(machine_deps, 'is_frozen', lambda: False)
        folder = tmp_path / 'bert_partial_onnx_fp16'
        folder.mkdir()
        with pytest.raises(ValueError) as caught:
            BertClassifier(str(folder), runtime='onnx')
        assert 'ONNX' in str(caught.value)
        assert 'export_onnx_bert.py' not in str(caught.value), 'the folder is there; nothing to unpack'
