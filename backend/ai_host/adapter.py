"""采析绘 as an agent-workspace host: the ONE place domain knowledge enters the framework.

Nothing here re-implements the engine. Facts come from the product's generated project map, tools
and skills are the existing registries converted to the framework's declarations, and the approval
flags reuse the product's own ``APPROVAL_TOOLS`` / ``ALWAYS_APPROVAL_TOOLS`` lists. A tool keeps its
handler signature ``(args, ctx)``, so migration is a declaration change, not a rewrite.
"""

from __future__ import annotations

from agent_workspace import DefaultHostAdapter
from agent_workspace.config import BY_KEY, LEGACY_KEYS
from agent_workspace.host import EventBus, HostEnvironment
from agent_workspace.settings import FileSettings
from agent_workspace.tools import CONTROL_TOOLS, generic_specs
from agent_workspace.types import SkillSpec, ToolSpec
from ai import environment as product_environment
from ai import files as product_files
from ai import skills as legacy_skills
from ai import tools as legacy_tools
from ai import validators as legacy_validators
from ai.context import project_facts
from core.config import Config
from runtime import account_context, policy, run_events
from runtime.settings import get_setting

#: framework key → the product setting that already owns it (``LEGACY_KEYS`` is the other direction).
_PRODUCT_KEY = {framework: product for product, framework in LEGACY_KEYS.items()}


class ProductSettings(FileSettings):
    """The product's settings win for the keys it already owns; the framework file holds the rest.

    This is the whole "settings migration": a user who set ``ai_max_tool_rounds`` in 采析绘 keeps that
    value in the workspace, and a key the product has never heard of lives in the workspace's own
    JSON. Nothing is copied at boot, so a later change in the product is seen on the next read.
    """

    def get(self, key: str, default=None):
        product = _PRODUCT_KEY.get(key)
        if product:
            value = get_setting(product)
            if value is not None:
                setting = BY_KEY.get(key)
                return setting.validate(value) if setting else value
        return super().get(key, default)

    def all(self) -> dict:
        values = super().all()
        for framework, product in _PRODUCT_KEY.items():
            value = get_setting(product)
            if value is not None:
                setting = BY_KEY.get(framework)
                values[framework] = setting.validate(value) if setting else value
        return values


#: Names the framework already serves itself (its own generic tools and control tools). The
#: product's tool of the same name is not re-declared: the framework's copy reads the same host facts
#: (``project_facts``) or performs the same generic read, and a duplicate declaration is refused.
FRAMEWORK_TOOLS = frozenset({spec.name for spec in generic_specs()} | set(CONTROL_TOOLS))


def _convert_tool(spec) -> ToolSpec:
    """One legacy tool as a framework declaration; approval flags come from the same lists."""
    return ToolSpec(
        spec.name,
        spec.description,
        spec.parameters,
        permission=str(getattr(spec, 'permission', 'read:project')),
        handler=_gated(spec),
        control=bool(getattr(spec, 'control', False)),
        mutating=spec.name in legacy_tools.APPROVAL_TOOLS,
        always_ask=spec.name in legacy_tools.ALWAYS_APPROVAL_TOOLS,
    )


def _convert_skill(spec) -> SkillSpec:
    return SkillSpec(
        id=spec.id,
        name_key=spec.name_key,
        description_key=spec.description_key,
        prompt=spec.prompt,
        context=tuple(spec.context),
        tools=tuple(spec.tools),
        requires=frozenset(spec.requires),
        suggested=tuple(spec.suggested),
        ask_policy=str(spec.ask_policy),
        builtin=bool(spec.builtin),
        local_only=bool(spec.local_only),
        version=int(spec.version),
        icon=str(getattr(spec, 'icon', 'spark')),
        name=str(getattr(spec, 'name', '')),
        description=str(getattr(spec, 'description', '')),
    )


class CaiXiHuiHost(DefaultHostAdapter):
    """The product's HostAdapter. Domain facts/tools/skills live here, never in the framework."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._settings = None
        self._bus = None

    def settings(self):
        if self._settings is None:
            self._settings = ProductSettings(self.data_dir() / 'settings.json')
        return self._settings

    def facts(self) -> dict:
        return {'project': project_facts()}

    def tools(self) -> list[ToolSpec]:
        return [_convert_tool(spec) for spec in legacy_tools.TOOLS.values() if spec.name not in FRAMEWORK_TOOLS]

    def skills(self) -> list[SkillSpec]:
        return [_convert_skill(spec) for spec in legacy_skills.BUILTIN.values()]

    def commands(self) -> dict:
        """`/init` belongs to the product: it reports the project map this host actually serves."""
        return {'init': self._command_init}

    @staticmethod
    def _command_init(_payload: dict) -> dict:
        facts = project_facts()
        return {
            'facts_chars': len(facts),
            'tools': len(legacy_tools.TOOLS),
            'skills': len(legacy_skills.BUILTIN),
        }

    def artifact_validators(self) -> dict:
        """The product's strict artifact validators, by kind.

        The framework runs these before storing a proposal and again before applying it, so a
        malformed workflow/memory draft is refused by name. They validate only; a validator that
        normalizes its payload (the old agent's ``Validation.payload``) still does so on the product
        side when applied.
        """
        return {kind: self._validator(kind) for kind in sorted(legacy_validators.registered_kinds())}

    @staticmethod
    def _validator(kind: str):
        def validate(payload: dict) -> list[str]:
            result = legacy_validators.check(kind, payload or {})
            if result is None or result.ok:
                return []
            return list(result.problems or [result.message])

        return validate

    # ── the machine this host runs on ────────────────────────────────────────

    def environment(self):
        kind = 'cloud' if Config.CLOUD_MODE else ('desktop' if product_environment.kind() == 'desktop' else 'local')
        return HostEnvironment(
            kind=kind,
            source_root=product_environment.code_root(),
            extra=product_environment.capabilities(),
        )

    def bind_account(self, account: str, lang: str = '') -> None:
        """A turn runs on its own thread: bind the account tree and the language there.

        ``paths.active()`` reads this context; without it a tool that writes (a dataset grant, a
        script, a monitor delivery) would write the local owner's tree for a signed-in account.
        """
        from i18n import set_lang

        account_context.bind(self._account_record(account))
        if lang:
            set_lang(lang)

    @staticmethod
    def _account_record(account: str):
        """The identity behind a user id: the registered row when accounts exist, else the owner."""
        if not account or account == 'default':
            return None
        from runtime.account_context import Account

        from services.accounts.service import get_account_service

        row = get_account_service().store.get_user(str(account))
        if not row:
            return None
        return Account(
            user_id=str(row['user_id']),
            username=str(row['username']),
            role=str(row['role']),
            must_change_password=bool(row['must_change_password']),
        )

    # ── the product's own services the engine delegates to ───────────────────

    def search(self, query: str, limit: int = 3, api_key: str = '') -> list[dict]:
        return list(product_files.search(api_key, str(query or ''), count=max(1, int(limit or 3))).get('results') or [])

    def fetch(self, url: str, api_key: str = '') -> str:
        page = product_files.fetch(api_key, str(url or ''))
        title = str(page.get('title') or '')
        content = str(page.get('content') or '')
        return f'{title}\n\n{content}'.strip() if title else content

    def command_allowlist(self) -> tuple[str, ...]:
        from ai.workspace import ALLOWED_COMMANDS

        return tuple(sorted(ALLOWED_COMMANDS))

    def import_table(self, path: str) -> dict:
        from ai import workspace as product_workspace

        return product_workspace.import_path(str(path or ''))

    # ── @ references ─────────────────────────────────────────────────────────

    def reference_candidates(self, account: str, query: str = '') -> list[dict]:
        """The product's own picker rows: skills, saved workflows, exports, datasets and runs.

        The framework merges these with its store-owned files/artifacts/conversations and applies
        the query, so this method only describes product objects; it never filters or pages.
        """
        from ai import knowledge
        from runtime import stores

        rows: list[dict] = []
        for skill in knowledge.catalog(limit=knowledge.MAX_LIMIT)['skills']:
            rows.append({'kind': 'skill', 'id': skill['id'], 'label': skill['title'], 'detail': skill['category']})
        for dataset in stores.get_dataset_store().list_datasets(limit=60):
            rows.append(
                {
                    'kind': 'dataset',
                    'id': str(dataset.get('dataset_id') or ''),
                    'label': str(dataset.get('name') or dataset.get('dataset_id') or ''),
                    'detail': f'{int(dataset.get("row_count") or 0)} 行',
                }
            )
        for saved in stores.get_workflow_manager().describe()[:40]:
            rows.append(
                {
                    'kind': 'workflow',
                    'id': str(saved.get('name') or ''),
                    'label': str(saved.get('name') or ''),
                    'detail': f'{int(saved.get("nodes") or 0)} 节点',
                }
            )
        for run in stores.get_run_store().run_ledger()[:40]:
            rows.append(
                {
                    'kind': 'run',
                    'id': str(run.get('id') or ''),
                    'label': str(run.get('workflow_name') or run.get('id') or ''),
                    'detail': f'{run.get("status") or ""} · {run.get("row_count") or 0} 行',
                }
            )
        from runtime import paths

        from services.exports.browser import list_exports

        for export in list_exports(paths.active().export_dir, limit=40):
            rows.append(
                {
                    'kind': 'export',
                    'id': str(export.get('name') or ''),
                    'label': str(export.get('name') or ''),
                    'detail': f'{int(export.get("size") or 0) // 1024} KB',
                }
            )
        return rows

    def resolve_dataset(self, dataset_id: str):
        from ai import reference_text

        return reference_text.dataset(str(dataset_id or ''))

    def resolve_run(self, run_id: str):
        from ai import reference_text

        return reference_text.run(str(run_id or ''))

    def resolve_reference(self, kind: str, identifier: str) -> str:
        from ai import reference_text

        reader = {
            'workflow': reference_text.workflow,
            'export': reference_text.export,
            'skill': reference_text.skill,
        }.get(str(kind or ''))
        return str(reader(str(identifier or '')) if reader else '')

    def recipes(self) -> list[dict]:
        """The product's ordered plans; the framework owns the run, evidence and tool mask."""
        from ai import recipes as product_recipes

        return [dict(recipe) for recipe in product_recipes.RECIPES]

    def apply_artifact(self, kind: str, payload: dict) -> dict:
        """The product applies each artifact through its own typed endpoint (workflow/memory/chart).

        The framework's generic apply door stays closed here rather than guessing a writer: a kind
        with no typed endpoint is refused by name, and the card's button is what actually applies.
        """
        raise NotImplementedError(f'artifacts of kind {kind} are applied through their own endpoint')

    def script_library(self, store):
        return _ProductScriptLibrary()

    def python_runtime(self):
        return _ProductPythonRuntime()

    # ── universally offered domain tools ─────────────────────────────────────

    def universal_tools(self) -> tuple[str, ...]:
        """The product's always-offered verbs (the old agent's UNIVERSAL_TOOLS).

        A skill names what is special to it; reading the project, the workflow file and the working
        folder, asking for dataset rows and proposing an apply are every turn's vocabulary.
        """
        return legacy_tools.UNIVERSAL_TOOLS

    def core_tools(self) -> tuple[str, ...]:
        """Strict mode's priority group: the verbs a turn cannot get unstuck without.

        Deliberately NOT all of ``UNIVERSAL_TOOLS``. Declaring twenty-one names here made the
        12-tool budget meaningless: the framework kept them all and checked the count afterwards, so
        a local model was offered 27 tools — none of them the active skill's own. "Offered to every
        turn" (``universal_tools``) is eligibility, not immunity; only the verb that unblocks a
        refused read and the one that loads a skill's body earn a guaranteed slot.
        """
        return ('request_dataset_access', 'skill_load')

    # ── run monitors ────────────────────────────────────────────────────────

    def event_bus(self):
        if self._bus is None:
            self._bus = EventBus()
            run_events.subscribe(self._on_run_event)
        return self._bus

    def _on_run_event(self, payload: dict) -> None:
        """One run fact, mapped once into the framework's monitor vocabulary.

        The bus is the product's; the monitor engine is the framework's. The mapping keeps the
        product's event names (its catalogue is what the panel offers) and gives the framework the
        keys it matches on — subject/status/console/row_count — never crawled text.
        """
        event = str(payload.get('event') or '')
        if event not in MONITOR_EVENTS:
            return
        owner = account_context.current()
        bus = getattr(self, '_bus', None)
        if bus is None:
            return
        bus.publish(
            event,
            {
                'account': owner.user_id if owner is not None else 'default',
                'subject': str(payload.get('run_id') or ''),
                'run_id': str(payload.get('run_id') or ''),
                'workflow': str(payload.get('workflow') or ''),
                'node_id': str(payload.get('node_id') or ''),
                'node_type': str(payload.get('node_type') or ''),
                'label': str(payload.get('label') or ''),
                'status': str(payload.get('status') or ''),
                'outcome': str(payload.get('outcome') or ''),
                'row_count': int(payload.get('rows') or 0),
                'console': str(payload.get('line') or ''),
                'done': int(payload.get('done') or 0),
                'total': int(payload.get('total') or 0),
                'failed': int(payload.get('failed') or 0),
                'skipped': int(payload.get('skipped') or 0),
            },
        )


MONITOR_EVENTS = ('run.started', 'node.finished', 'run.finished', 'run.log')


def _gated(spec):
    """The product's cloud / Python / machine-authority gate, at the ONE door tools enter.

    The framework owns approval and offering; these refusals are domain facts it cannot know (a
    cloud host has no user filesystem, inline Python is machine-level). Wrapping here keeps every
    existing handler unchanged instead of re-checking inside 40 tools.
    """

    def run(args, ctx):
        from ai.errors import AIError

        permission = str(getattr(spec, 'permission', '') or '')
        if permission == 'read:code' and (
            Config.CLOUD_MODE
            or not (get_setting('ai_allow_code_context') and product_environment.capabilities()['local_source'])
        ):
            raise AIError('ai.codeCloudRefused', kind='capability')
        if permission in ('read:python', 'write:python', 'exec:python'):
            if Config.CLOUD_MODE:
                raise AIError('ai.pythonCloud', kind='capability')
            if not (get_setting('ai_allow_python') and product_environment.capabilities()['code_plugins']):
                raise AIError('ai.pythonDisabled', kind='capability')
            inline = spec.name == 'python_run' and bool(str((args or {}).get('code') or '').strip())
            if (inline or permission == 'write:python' or spec.name in ('python_read', 'python_files')) and not (
                policy.may_administer_machine()
            ):
                raise AIError(policy.machine_refusal_key(), kind='capability')
        if permission in ('read:files', 'write:files', 'exec:cmd') and (
            Config.CLOUD_MODE or not product_environment.capabilities()['user_files']
        ):
            raise AIError('ai.workspaceCloud', kind='capability')
        runtime_ctx = dict(ctx or {})
        runtime_ctx.setdefault('provider', str(runtime_ctx.get('provider_id') or ''))
        return spec.handler(args or {}, runtime_ctx)

    run.__wrapped__ = spec.handler
    return run


class _ProductScriptLibrary:
    """``ScriptLibrary``'s interface over the product's ONE saved-script library."""

    def all(self, _account: str) -> list[dict]:
        from services import python_scripts

        return python_scripts.all_scripts()

    def get(self, _account: str, script_id: str) -> dict:
        from services import python_scripts

        return python_scripts.find_script(str(script_id or '')) or {}

    def code(self, _account: str, script_id: str) -> str:
        return str(self.get(_account, script_id).get('code') or '')

    def save(self, _account: str, payload: dict) -> dict:
        from services import python_scripts

        return python_scripts.save_script(dict(payload or {}))

    def fork(self, _account: str, script_id: str) -> dict:
        from services import python_scripts

        return python_scripts.fork_script(str(script_id or ''))

    def delete(self, _account: str, script_id: str) -> bool:
        from services import python_scripts

        return python_scripts.delete_script(str(script_id or ''))


class _ProductPythonRuntime:
    """The framework Python tools over the product's interpreter discovery and runner."""

    def status(self, _settings=None) -> dict:
        from services import python_runtime

        found = python_runtime.interpreter()
        return {
            'available': bool(found.get('available')),
            'interpreter': str(found.get('path') or ''),
            'version': str(found.get('version') or ''),
            'enabled': bool(get_setting('ai_allow_python')),
            'contract': {
                'input': 'CIXI_INPUT (path to JSON Lines)',
                'output': 'CIXI_OUTPUT (path to JSON Lines)',
                'args': 'CIXI_ARGS (JSON in the environment)',
            },
            'sandbox': False,
        }

    def run_code(self, code, *, rows=None, args=None, timeout=10, python_bin='', cancel_event=None, **kwargs) -> dict:
        from services import python_runtime

        # The product discovers its own interpreter (`ai_python_path`, mapped from the framework's
        # `python.path`); the engine's explicit binary is therefore already the same answer.
        del python_bin
        result = python_runtime.run_code(
            str(code or ''),
            list(rows or []),
            dict(args or {}),
            timeout=int(timeout or 10),
            cancel_event=cancel_event,
            max_rows=int(kwargs.get('max_rows') or 1000),
        )
        result.setdefault('row_count', len(result.get('rows') or []))
        return result
