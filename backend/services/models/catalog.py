"""The read-only model catalogue shared by the picker, the node executor and the AI tools.

There is no process cache here: a newly dropped manifest or an edited registry must be visible on the
next call. The cost is a directory scan and a small JSON read, far below the cost of loading a model.
"""

from services.models import discovery, probe
from services.models.manifest import ModelManifest


class UnknownModelError(LookupError):
    """A node or tool named a model this machine does not have; refuse, never pick option #0."""


def all_models() -> list[ModelManifest]:
    return discovery.load()


def get(model_id: str) -> ModelManifest:
    """One model by id, or a refusal that names the id that was asked for."""
    wanted = str(model_id or '').strip()
    for manifest in all_models():
        if manifest.id == wanted:
            return manifest
    raise UnknownModelError(f'unknown model {wanted!r}; call models_catalog for the registered ids')


def find(model_id: str) -> ModelManifest | None:
    """The non-raising form for a picker that wants to show an off-list value as itself."""
    wanted = str(model_id or '').strip()
    for manifest in all_models():
        if manifest.id == wanted:
            return manifest
    return None


def for_task(task: str) -> list[ModelManifest]:
    wanted = str(task or '').strip()
    return [model for model in all_models() if wanted in (model.task, model.operation) or wanted in model.default_for]


def default_for_declared(task: str) -> str:
    """A manifest that explicitly claims ``default_for`` for this task, or ''."""
    wanted = str(task or '').strip()
    for model in all_models():
        if wanted in model.default_for:
            return model.path
    return ''


def default_for(task: str) -> str:
    """The recommended model path for one task, or '' when nothing is registered for it."""
    wanted = str(task or '').strip()
    declared = default_for_declared(wanted)
    if declared:
        return declared
    models = for_task(wanted)
    return models[0].path if models else ''


def legacy_rows() -> list[dict]:
    """The exact shape ``/api/models`` and ``default_model_path_for`` have always consumed.

    The legacy endpoint deliberately shows ONLY rows from the hand-edited registry: existing tests
    and saved panels depend on its "missing file means empty list" contract. The richer catalogue is
    served by ``public_rows`` and used by the AI tools and the new model picker.
    """
    return [model.to_legacy() for model in all_models() if model.meta.get('legacy')]


def default_model_path_for(operation: str) -> str:
    """The registry path of the FIRST model tagged ``operation``, or ``''`` when none is registered.

    This is what makes a default ``bert`` node actually mean bert: when a node names no model, the
    executor resolves the operation's registered default here (registry order is the operator's
    preference — e.g. the “推荐” tendency model is listed first). ``''`` means "nothing to load",
    which the executor treats as bert-unavailable and degrades to the general mode with a printed line.

    It lived in ``api/config.py`` until a node needed it — which meant the executor imported the
    HTTP layer. The answer is a domain fact, so it lives beside the catalogue it reads.
    """
    want = str(operation or '').strip()
    declared = default_for_declared(want)
    if declared:
        return declared
    for model in legacy_rows():
        if model['operation'] == want:
            return model['path']
    return ''


def public_rows() -> list[dict]:
    """The rich catalogue, including this machine's runnable verdict for each model."""
    state = probe.runtime_state(include_cuda=False)
    rows = []
    for model in all_models():
        ok, why_not = probe.runnable(model, state)
        rows.append(model.public(runnable=ok, why_not=why_not))
    return rows


def runnable_or_refuse(model_id: str) -> ModelManifest:
    """Resolve and check one model before any weights are loaded or any rows are read."""
    manifest = get(model_id)
    ok, why_not = probe.runnable(manifest)
    if not ok:
        raise UnknownModelError(why_not)
    return manifest
