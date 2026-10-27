"""Machine requirements: the tokens a crawl mode may carry, and whether THIS machine meets them.

The token travels to the browser as a name (``cap.requires.<token>``) so the panel says it in the
canvas's own language, while the verdict is computed here from the running OS and the cloud switch.
Kept apart from the matrix so a mode's declaration and the machine's answer can be read (and
tested) independently — the same separation ``capabilities/`` exists for.
"""

from core import machine

#: A machine requirement a crawl mode can carry, by name. The token is deliberately not a sentence:
#: it goes to the browser, which says it in whichever language the canvas is reading
#: (``cap.requires.<token>``), and the server answers whether THIS machine meets it.
#:
#: ``windows_desktop`` is the one that exists because the app was written on Windows and deployed on a
#: Linux server: 红果评论 drives the desktop player through a proxy whose CA we install into the Windows
#: certificate store, so it needs a window, that store, and a machine nobody else is sharing.
REQUIREMENTS = ('windows_desktop',)

#: The words for each requirement, spelled out as literal catalogue keys (a computed ``f'cap.requires.{t}'``
# is how a refusal ends up printing its own key — the reachability scan can only ask about names it sees).
#: Public because the contract test walks it against :data:`REQUIREMENTS` and against the JS copy.
REQUIREMENT_LABELS = {'windows_desktop': 'cap.requiresWindowsDesktop'}


def requirement_met(token: str, system: str | None = None, cloud: bool | None = None) -> bool:
    """Whether this machine can run a mode that asks for ``token``.

    An unknown token answers YES: refusing a mode because a name was mis-typed would hide a working
    feature, and the mode's own executor still refuses by name when its real dependency is missing.
    """
    if token == 'windows_desktop':
        return machine.is_windows(system) and not (cloud_is() if cloud is None else cloud)
    return True


def cloud_is() -> bool:
    """The cloud switch, read late so an import of this matrix never drags ``config`` in."""
    from core.config import Config

    return bool(Config.CLOUD_MODE)


def machine_requirements(system: str | None = None, cloud: bool | None = None) -> dict:
    """Every requirement, answered for the machine running this server.

    One payload, one answer: the panel greys a mode out of it and the pre-run gate refuses from the same
    numbers, so the two cannot disagree about whether the user's click has any chance.
    """
    return {token: requirement_met(token, system, cloud) for token in REQUIREMENTS}


def requirement_label_key(token: str) -> str:
    """The catalogue key naming a requirement — a literal per token, never a computed one.

    Computed keys are how a refusal prints ``cap.requires.windows``: the reachability scan only asks
    about keys it can see spelled out, so the spelling lives here and the test walks
    :data:`REQUIREMENTS` against it.
    """
    return REQUIREMENT_LABELS.get(token, '')
