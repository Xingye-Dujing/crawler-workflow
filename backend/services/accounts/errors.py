"""A refusal that names its reason, translated at the HTTP boundary.

The account layer never builds a user-facing sentence: it raises a catalogue key plus the values
that fill its placeholders, and the API route renders it with ``i18n.t`` in the request's language.
That keeps one wording in one domain file and lets a unit test assert the reason, not a sentence.
"""


class AccountError(Exception):
    """A named refusal. ``key`` lives in ``i18n_catalog/accounts.py``."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params
