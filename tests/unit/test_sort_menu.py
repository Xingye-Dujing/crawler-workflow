"""The hover-menu helper and douyin's sort choice, with no browser.

Two separate claims are pinned here, because they fail differently:

* :func:`crawlers.engine.menu.choose` decides *what to say* when a choice cannot be made — no
  opener on the page, the word is not in the menu, the menu item would not click, and "the page
  never turned over after a click that did land";
* :meth:`crawlers.video.DouyinCrawler._apply_sort` decides *whether to ask at all* — the default
  order is what the page already shows, so 综合排序 must press nothing (waiting for a change that
  cannot come would burn the budget on a no-op) — and what the crawl records afterwards: the chosen
  order goes into the resume cursor, because **no URL carries it** (measured: the address stays
  ``/search/IU?type=video`` whichever item is picked).

``ActionChains`` needs a real driver, so the hover itself is proven in the device tier
(``tests/integration/test_hover_menu.py``, a local page with a CSS-hover menu); this file drives
the helper's two primitives and the crawler's decisions.
"""

import pytest

from crawlers.engine import menu
from crawlers.video import DouyinCrawler

pytestmark = pytest.mark.unit


class _Node:
    #: The real page's menu items share one (hashed) class, which is how ``option_texts``
    #: enumerates them; the fake carries that property rather than a name that would pass anywhere.
    CLASS = 'eXMmo3JR'

    def __init__(self, text, clickable=True):
        self.text = text
        self._clickable = clickable
        self.clicks = 0

    def click(self):
        self.clicks += 1
        if not self._clickable:
            raise RuntimeError('element not interactive')

    def get_attribute(self, name):
        return self.CLASS if name == 'class' else ''


class _FakeDriver:
    """A page whose visible text is a fixed set — enough to answer "is this word there?"."""

    def __init__(self, texts, clickable=True):
        self.nodes = {text: [_Node(text, clickable)] for text in texts}
        self.queries = []

    def find_elements(self, by, selector):
        self.queries.append(selector)
        if "contains(@class,'" in selector:
            return [nodes[0] for nodes in self.nodes.values()]
        for text, nodes in self.nodes.items():
            if selector.endswith(f"='{text}']"):
                return nodes
        return []


class TestChoose:
    """The decision half: what to report, and when to keep waiting.

    The hover itself needs a real browser (``ActionChains`` drives the pointer), so it is
    stubbed here and proven in the device tier on a local page; what this file pins is that a
    choice the page cannot honour is **named** rather than swallowed.
    """

    @pytest.fixture(autouse=True)
    def _stub_hover(self, monkeypatch):
        """Hover succeeds iff the opener word is on the page — which is the real rule."""
        self.hovered = []

        def fake_hover(driver, text, settle=1.2):
            self.hovered.append(text)
            return bool(driver.find_elements('xpath', menu.TEXT_XPATH % text))

        monkeypatch.setattr(menu, 'hover', fake_hover)

    def test_a_choice_needs_the_opener_and_reports_when_there_is_none(self):
        answer = menu.choose(_FakeDriver(['搜索']), '筛选', '最新发布', snapshot=lambda: ['a'])
        assert answer['ok'] is False and answer['reason'] == 'no_opener', answer
        assert self.hovered == ['筛选'], 'the opener is the first thing it tries, not the last'

    def test_a_word_the_menu_does_not_offer_is_named_with_what_it_does_offer(self):
        """The two refusals a user can act on are different: 「the control is gone」 says the page
        changed shape, 「this option is not in it」 says the site renamed the choice — and the list
        that comes back has to be the menu's own words, which is why the caller names a word it
        knows is there (``sample_text``) instead of searching for the missing one."""
        driver = _FakeDriver(['筛选', '综合排序', '最新发布'])
        answer = menu.choose(driver, '筛选', '最多分享', snapshot=lambda: ['a'], sample_text='综合排序')
        assert answer['ok'] is False and answer['reason'] == 'missing', answer
        assert '最新发布' in answer['options'], answer['options']
        assert '最多分享' not in answer['options'], answer['options']

    def test_an_item_that_refuses_to_be_clicked_is_not_reported_as_a_missing_one(self):
        driver = _FakeDriver(['筛选', '最新发布'], clickable=False)
        answer = menu.choose(driver, '筛选', '最新发布', snapshot=lambda: ['a'])
        assert answer['reason'] == 'no_handle', answer

    def test_a_pick_that_changes_nothing_is_reported_rather_than_assumed(self):
        """Measured on the live site: choosing 不限, which already is the value, leaves the list
        exactly as it was. That is a success with ``changed=False``, not a silent failure — and a
        helper that returned the two alike would let the crawler claim an order it never applied."""
        driver = _FakeDriver(['筛选', '最新发布'])
        answer = menu.choose(driver, '筛选', '最新发布', snapshot=lambda: ['x'], timeout=0.2, poll=0.05)
        assert answer['ok'] is True and answer['changed'] is False, answer
        assert driver.nodes['最新发布'][0].clicks == 1

    def test_the_wait_ends_on_the_evidence_the_caller_chose(self):
        state = {'ids': ['a', 'b']}
        driver = _FakeDriver(['筛选', '最新发布'])

        def flip():
            state['ids'] = ['c', 'd']
            return state['ids']

        driver.nodes['最新发布'][0].click = flip
        answer = menu.choose(driver, '筛选', '最新发布', snapshot=lambda: state['ids'], timeout=1.0, poll=0.05)
        assert answer['ok'] is True and answer['changed'] is True, answer


class TestDouyinSort:
    @pytest.fixture
    def crawler(self, monkeypatch):
        made = DouyinCrawler.__new__(DouyinCrawler)
        made.driver = _FakeDriver(['筛选', '综合排序', '最新发布', '最多点赞'])
        made._cursor = {}
        monkeypatch.setattr(made, 'mark_position', lambda **kw: made._cursor.update(kw))
        monkeypatch.setattr(DouyinCrawler, '_card_ids', lambda self: ['1', '2'])
        return made

    def test_the_default_order_presses_nothing(self, crawler, monkeypatch):
        calls = []
        monkeypatch.setattr(menu, 'choose', lambda *a, **k: calls.append(a))
        for value in (None, '', 'general', '  general '):
            crawler._apply_sort(value)
        assert calls == [], 'clicking the item already in force waits for a change that cannot come'
        assert crawler._cursor == {}, 'an order that was not applied must not be recorded'

    def test_an_order_is_applied_by_the_words_the_site_uses(self, crawler, monkeypatch):
        seen = []

        def fake_choose(driver, opener, option, snapshot=None, **kwargs):
            seen.append((opener, option, kwargs.get('sample_text')))
            return {'ok': True, 'reason': '', 'changed': True}

        monkeypatch.setattr(menu, 'choose', fake_choose)
        crawler._apply_sort('most_liked')
        assert seen == [('筛选', '最多点赞', '综合排序')], seen
        assert crawler._cursor == {'sort': 'most_liked'}, 'the cursor is the only record of the order'

    def test_a_refused_order_is_said_in_the_words_that_name_the_failure(self, crawler, monkeypatch):
        """Three different refusals, three different repairs — and none of them is "keep crawling".

        Continuing on 综合排序 after a failed pick would file a table under a claim this crawl
        never made, which is the same class of harm as a wall answered with an empty table.
        """
        for reason, needle in (
            ('no_opener', '筛选'),
            ('missing', '最新发布'),
            ('no_handle', '最新发布'),
        ):

            def refused_choice(*_args, _reason=reason, **_kwargs):
                return {'ok': False, 'reason': _reason, 'changed': False}

            monkeypatch.setattr(menu, 'choose', refused_choice)
            with pytest.raises(RuntimeError) as refused:
                crawler._apply_sort('newest')
            assert needle in str(refused.value), (reason, refused.value)
            assert crawler._cursor == {}, 'a crawl that never got the order must not claim it'

    def test_an_order_that_is_not_a_choice_is_refused_by_name(self, crawler, monkeypatch):
        """``sort`` is a select, so 「最热」 is not a variant of 最多点赞 — the panel cannot send it,
        and a hand-written workflow that does must be told which words are real."""
        monkeypatch.setattr(menu, 'choose', lambda *a, **k: pytest.fail('must not touch the page'))
        with pytest.raises(ValueError) as refused:
            crawler._apply_sort('最热')
        assert '最热' in str(refused.value) and 'most_liked' in str(refused.value), refused.value
