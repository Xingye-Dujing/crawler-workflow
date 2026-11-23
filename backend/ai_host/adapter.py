"""采析绘 as an agent-workspace host: the ONE place domain knowledge enters the framework.

Nothing here re-implements the engine. Facts come from the product's generated project map, tools
and skills are the existing registries converted to the framework's declarations, and the approval
flags reuse the product's own ``APPROVAL_TOOLS`` / ``ALWAYS_APPROVAL_TOOLS`` lists. A tool keeps its
handler signature ``(args, ctx)``, so migration is a declaration change, not a rewrite.
"""

from __future__ import annotations

from agent_workspace import DefaultHostAdapter
from agent_workspace.tools import CONTROL_TOOLS, generic_specs
from agent_workspace.types import SkillSpec, ToolSpec
from ai import skills as legacy_skills
from ai import tools as legacy_tools
from ai import validators as legacy_validators
from ai.context import project_facts

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
        handler=spec.handler,
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

    def facts(self) -> dict:
        return {'project': project_facts()}

    def tools(self) -> list[ToolSpec]:
        return [_convert_tool(spec) for spec in legacy_tools.TOOLS.values() if spec.name not in FRAMEWORK_TOOLS]

    def skills(self) -> list[SkillSpec]:
        return [_convert_skill(spec) for spec in legacy_skills.BUILTIN.values()]

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
