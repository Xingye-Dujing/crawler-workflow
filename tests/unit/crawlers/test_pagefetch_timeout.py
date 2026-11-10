"""The in-page fetch borrows the DRIVER's script timeout, so it has to give it back.

``set_script_timeout`` is a property of the WebDriver session, not of one call. Every entry point here
set it to the fetch's own (short) value and never restored it, so every later ``execute_script`` on
that session inherited it — a scroll or a DOM probe three nodes later timed out for a reason that
belonged to a fetch, and nothing in the message said so. ``_script_timeout`` now brackets the call.

A fake driver records every value it was given: the assertion is that the sequence STARTS at the
fetch's value and ENDS at the session's own — including when the call raises, which is the case that
matters most, because a timed-out script leaves a live driver behind.
"""

import pytest

from crawlers.engine import pagefetch, popup

pytestmark = pytest.mark.unit

FETCH_TIMEOUT = 25.0


class _FakeDriver:
    """Records the script timeout on every set, and answers one canned async result."""

    def __init__(self, answer=None, raises=None):
        self.timeouts = []
        self.answer = answer
        self.raises = raises

    def set_script_timeout(self, value):
        self.timeouts.append(value)

    def execute_async_script(self, *_args, **_kwargs):
        if self.raises is not None:
            raise self.raises
        return self.answer


class TestTheScriptTimeoutGoesBack:
    def test_fetch_json_restores_what_the_session_had(self):
        driver = _FakeDriver(answer={'code': 0})
        pagefetch.fetch_json(driver, 'https://example.com/api', timeout=FETCH_TIMEOUT)
        assert driver.timeouts[0] == FETCH_TIMEOUT, 'the fetch applies its own timeout'
        assert driver.timeouts[-1] == pagefetch._DEFAULT_SCRIPT_TIMEOUT, (
            'the session must get its own timeout back, or every later script inherits the fetch one'
        )

    def test_fetch_restores_even_though_it_answers_a_status(self):
        driver = _FakeDriver(answer='{"status": 200, "body": "{}", "error": ""}')
        pagefetch.fetch(driver, 'https://example.com/api', timeout=FETCH_TIMEOUT)
        assert driver.timeouts[-1] == pagefetch._DEFAULT_SCRIPT_TIMEOUT

    def test_fetch_text_restores_when_the_call_raises(self):
        driver = _FakeDriver(raises=RuntimeError('script timeout'))
        assert pagefetch.fetch_text(driver, 'https://example.com/api', timeout=FETCH_TIMEOUT).startswith('ERR ')
        assert driver.timeouts[-1] == pagefetch._DEFAULT_SCRIPT_TIMEOUT

    def test_fetch_json_restores_when_the_call_raises(self):
        driver = _FakeDriver(raises=RuntimeError('script timeout'))
        assert pagefetch.fetch_json(driver, 'https://example.com/api', timeout=FETCH_TIMEOUT) == {}
        assert driver.timeouts[-1] == pagefetch._DEFAULT_SCRIPT_TIMEOUT


class TestThePopupLoopRestoresItToo:
    PROMPT = popup.Prompt(
        key='first-run',
        selector='.dialog',
        markers=('确定',),
        choose=('确定',),
    )

    def test_no_prompts_does_not_touch_the_timeout_at_all(self):
        driver = _FakeDriver(answer={'clicked': None, 'matched': None, 'seen': []})
        assert popup.dismiss(driver, [], tick=0.01, tries=1) == []
        assert driver.timeouts == []

    def test_a_matched_prompt_restores_the_session_value(self, monkeypatch):
        """It used to set the value per ATTEMPT and never put it back, so the loop's short
        tick-derived value stayed for the whole session."""
        driver = _FakeDriver(answer={'clicked': '确定', 'matched': '确定', 'seen': []})
        monkeypatch.setattr(popup.time, 'sleep', lambda _seconds: None)
        popup.dismiss(driver, [self.PROMPT], tick=0.1, tries=1)
        assert driver.timeouts[-1] == pagefetch._DEFAULT_SCRIPT_TIMEOUT
