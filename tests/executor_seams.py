"""Forward an app-level test patch to the module a node executor resolves it in.

Node executors live in ``nodes/executors/*`` and hold their own module globals (``get_crawler``,
``add_log``, ``network_probe``…). Tests written before that split patch ``app.<name>``; ``forward``
installs a call-time lookup on the plugin's attribute, so an existing patch of the app module still
means the same thing without the plugin ever importing Flask.
"""


def forward(monkeypatch, module, name: str, provider) -> None:
    """Make ``module.<name>`` call ``provider.<name>`` — resolved at call time, not now."""

    def _call(*args, **kwargs):
        return getattr(provider, name)(*args, **kwargs)

    monkeypatch.setattr(module, name, _call)
