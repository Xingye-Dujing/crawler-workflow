"""One failure type for the AI subsystem.

``AIError`` carries a translation key, its parameters and a stable ``kind``. The HTTP layer
turns it into either a JSON envelope (before the stream starts) or an ``error`` SSE event (after
it started); neither path prints the key's raw text, so a missing translation is visible as a
key rather than as an untranslated English sentence.
"""

from i18n import t


class AIError(Exception):
    """A refusal or transport failure with a stable machine-readable kind."""

    def __init__(self, key: str, kind: str = 'error', **params):
        self.key = key
        self.kind = kind
        self.params = params
        super().__init__(t(key, **params) if params else t(key))

    def localized(self) -> str:
        return t(self.key, **self.params) if self.params else t(self.key)

    def as_dict(self) -> dict:
        return {'ok': False, 'kind': self.kind, 'error': self.localized(), 'key': self.key}


class AIProviderError(AIError):
    """A provider answered, but not with an answer."""

    def __init__(self, key: str, kind: str = 'network', status: int | None = None, **params):
        self.status = status
        super().__init__(key, kind=kind, **params)
