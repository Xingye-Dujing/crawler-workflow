"""What this machine can actually run, answered without downloading or importing everything.

``find_spec`` is the cheap answer for an uninstalled package; importing torch just to discover CUDA
costs hundreds of megabytes, so that happens only when a caller asks for the capability report. A
model whose weights folder is absent refuses BY NAME with the path that was searched -- never a quiet
fallback to another model in the catalogue.
"""

import contextlib
import os
import sys
from importlib.util import find_spec

from services.models.manifest import ModelManifest

#: What each family needs before a node may load it. The keys are Python distributions, checked by
#: module name; the '' key means the family is dependency-free.
FAMILY_REQUIRES = {
    'text_classification': ('torch', 'transformers'),
    'token_classification': ('torch', 'transformers'),
    'encoder': ('sentence_transformers',),
    'reranker': ('sentence_transformers',),
    'zero_shot': ('torch', 'transformers'),
    'sklearn_text': (),
    'tabular': (),
}


def _importable(name: str) -> bool:
    """Would ``import name`` work here -- answered without importing it (see analyzers.sentiment)."""
    if name in sys.modules:
        return True
    with contextlib.suppress(ValueError):
        return find_spec(name) is not None
    return False


def runtime_state(*, include_cuda: bool = True) -> dict:
    """A per-machine capability map; local only, never cached across processes."""
    state = {
        'torch': _importable('torch'),
        'transformers': _importable('transformers'),
        'onnxruntime': _importable('onnxruntime'),
        'tokenizers': _importable('tokenizers'),
        'sentence_transformers': _importable('sentence_transformers'),
        'cuda': False,
        'device': '',
        'free_vram_mb': 0,
    }
    if include_cuda and state['torch']:
        with contextlib.suppress(Exception):
            import torch

            state['cuda'] = bool(torch.cuda.is_available())
            if state['cuda']:
                free, total = torch.cuda.mem_get_info()
                state['free_vram_mb'] = round(free / (1024 * 1024))
                state['total_vram_mb'] = round(total / (1024 * 1024))
                state['device'] = torch.cuda.get_device_name(0)
    return state


def _path_ready(manifest: ModelManifest) -> tuple[bool, str]:
    """Whether the weights themselves are present; ONNX and HF folders are both accepted."""
    path = manifest.path
    if not path:
        return False, f'{manifest.source_of_truth()}: no path'
    if os.path.isdir(path):
        if manifest.family == 'text_classification' and not any(
            os.path.isfile(os.path.join(path, name)) for name in ('config.json', 'model.onnx', 'model.safetensors')
        ):
            return False, f'{path}: no config.json, model.onnx or model.safetensors'
        return True, ''
    if os.path.isfile(path):
        return True, ''
    return False, f'{path}: weights are not on this machine; run the project-local downloader first'


def runnable(manifest: ModelManifest, state: dict | None = None) -> tuple[bool, str]:
    """``(ok, why_not)``: an explicit model the host cannot run is named, never substituted."""
    state = state if state is not None else runtime_state(include_cuda=False)
    requirements = FAMILY_REQUIRES.get(manifest.family)
    if requirements is None:
        return False, f'{manifest.source_of_truth()}: unknown family {manifest.family!r}'
    missing = [name for name in requirements if not state.get(name)]
    # A packaged build has no torch but runs the ONNX graph; only accept that when the graph is here.
    onnx_ok = bool(state.get('onnxruntime') and state.get('tokenizers')) and os.path.isfile(
        os.path.join(manifest.path, 'model.onnx')
    )
    if missing and not (manifest.family == 'text_classification' and onnx_ok):
        return False, f'{manifest.source_of_truth()}: missing {", ".join(missing)} on this machine'
    return _path_ready(manifest)
