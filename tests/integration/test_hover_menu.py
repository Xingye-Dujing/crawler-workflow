"""Real Chrome: a hover-only menu can be opened, read and picked — and a click closes it.

The unit tier proves what :func:`crawlers.engine.menu.choose` *reports*; only a browser proves the
two mechanisms the douyin result page is built on and that the crawler now leans on:

* the panel's items do not exist until the pointer arrives (the page mounts them, which is why an
  absent word means "not offered" rather than "hidden"), so ``ActionChains.move_to_element`` is
  not a nicety here — without it the pick has no handle;
* **clicking** the corner word closes what hovering opened (measured on the live site: read the
  menu after a click and it is empty again), so an implementation written as "click, then read"
  would find nothing at the exact moment it expects everything.

The fixture is local and mounts the menu on ``mouseover`` for the same reason the site's does:
the honest test of "did the pointer get there" is a page that only answers to a pointer.
"""

import pytest

from crawlers.engine import menu

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>hover menu fixture</title></head>
<body>
<div id="opener">筛选</div>
<div id="list"><span class="row">a</span><span class="row">b</span></div>
<script>
  // The corner word only ever *closes* the panel; opening is the pointer's job.
  document.getElementById('opener').addEventListener('click', function () {
      var box = document.getElementById('panel');
      if (box) { box.remove(); }
  });
  document.getElementById('opener').addEventListener('mouseover', function () {
      if (document.getElementById('panel')) { return; }
      var box = document.createElement('div');
      box.id = 'panel';
      ['综合排序', '最新发布', '最多点赞'].forEach(function (word) {
          var item = document.createElement('span');
          item.className = 'menuItem';
          item.textContent = word;
          item.addEventListener('click', function () {
              document.getElementById('list').innerHTML =
                  '<span class="row">' + word + '</span><span class="row">x</span>';
          });
          box.appendChild(item);
      });
      document.body.appendChild(box);
  });
</script>
</body></html>
"""

#: A second page where 筛选 sits under a sticky header that covers its geometric centre. This is the
#: headless failure measured on douyin's live result page: ``move_to_element`` aims at the centre,
#: the header takes the pointer, and the hover-wired panel never mounts. The JS dispatch inside
#: :func:`crawlers.engine.menu.hover` reaches the node itself and is the only thing that opens it.
PAGE_COVERED = """<!doctype html>
<html><head><meta charset="utf-8"><title>covered hover menu fixture</title></head>
<body>
<div id="opener" style="position:absolute; top:40px; left:40px; width:120px; height:30px; z-index:1;">筛选</div>
<div id="cover" style="position:absolute; top:0; left:0; width:600px; height:200px; z-index:2;"></div>
<div id="list"><span class="row">a</span><span class="row">b</span></div>
<script>
  document.getElementById('opener').addEventListener('mouseover', function () {
      if (document.getElementById('panel')) { return; }
      var box = document.createElement('div');
      box.id = 'panel';
      ['综合排序', '最新发布', '最多点赞'].forEach(function (word) {
          var item = document.createElement('span');
          item.className = 'menuItem';
          item.textContent = word;
          box.appendChild(item);
      });
      document.body.appendChild(box);
  });
</script>
</body></html>
"""


def rows(driver) -> list:
    return [element.text for element in driver.find_elements('css selector', '.row')]


@pytest.fixture(scope='module')
def hovered_browser():
    """One Chrome for the module: every case is a page load, not a session."""
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as exc:
        pytest.skip(f'Chrome/chromedriver unavailable: {exc}')
    try:
        yield driver
    finally:
        driver.quit()


@pytest.fixture
def menu_page(hovered_browser, tmp_path):
    page = tmp_path / 'hover-menu.html'
    page.write_text(PAGE, encoding='utf-8')
    hovered_browser.get(page.as_uri())
    return hovered_browser


@pytest.fixture
def covered_page(hovered_browser, tmp_path):
    page = tmp_path / 'hover-menu-covered.html'
    page.write_text(PAGE_COVERED, encoding='utf-8')
    hovered_browser.get(page.as_uri())
    return hovered_browser


class TestTheHoverMenu:
    def test_the_panel_is_not_in_the_page_until_the_pointer_arrives(self, menu_page):
        assert menu.nodes_with_text(menu_page, '最新发布') == [], (
            'a fixture that pre-renders the menu proves nothing about hovering'
        )
        assert menu.hover(menu_page, '筛选') is True
        assert menu.nodes_with_text(menu_page, '最新发布'), 'the hover never reached the page'

    def test_choose_opens_reads_and_waits_until_the_page_turns_over(self, menu_page):
        answer = menu.choose(menu_page, '筛选', '最新发布', snapshot=lambda: rows(menu_page), timeout=6.0)
        assert answer['ok'] is True and answer['changed'] is True, answer
        assert rows(menu_page) == ['最新发布', 'x'], rows(menu_page)

    def test_the_offered_words_are_read_from_the_open_panel(self, menu_page):
        menu.hover(menu_page, '筛选')
        assert menu.option_texts(menu_page, '综合排序') == ['综合排序', '最新发布', '最多点赞']

    def test_a_click_on_the_corner_word_closes_it_and_the_next_hover_reopens_it(self, menu_page):
        """The measured page behaviour, kept as a test because it dictates the implementation:

        every pick must re-hover. A crawler that hoisted the hover out of the loop would press a
        stale handle on the second choice and read the silence as "the order did not change".

        And the pointer has to actually *travel*: a mouse event only fires on a change of
        position, so re-hovering the word the cursor is already sitting on reopens nothing. That
        is not a fixture quirk to code around — after a pick the pointer is on the chosen item,
        elsewhere on the page, which is why the next :func:`menu.hover` does fire in a real crawl.
        """
        from selenium.webdriver.common.action_chains import ActionChains

        assert menu.hover(menu_page, '筛选') is True
        menu.pick(menu_page, '筛选')
        assert menu.nodes_with_text(menu_page, '最多点赞') == [], 'a click should have closed the panel'
        ActionChains(menu_page).move_to_element(menu_page.find_element('css selector', '#list')).perform()
        assert menu.hover(menu_page, '筛选') is True
        assert menu.pick(menu_page, '最多点赞') is True

    def test_a_word_the_panel_does_not_offer_is_named_without_a_click_being_blamed(self, menu_page):
        answer = menu.choose(menu_page, '筛选', '最多分享', snapshot=lambda: rows(menu_page), sample_text='综合排序')
        assert answer['ok'] is False and answer['reason'] == 'missing', answer
        assert answer['options'] == ['综合排序', '最新发布', '最多点赞'], answer['options']
        assert rows(menu_page) == ['a', 'b'], 'a refused choice must not have touched the list'


class TestAHoverMenuWhoseWordIsCovered:
    """The headless failure that :func:`crawlers.engine.menu.hover` now defends against.

    Measured on douyin's live result page: an overlay can cover the opener's geometric centre, so
    ``ActionChains.move_to_element`` — which dispatches a real pointer *at that coordinate* — reaches
    the overlay instead, the hover-wired panel never mounts, and the crawler reads the one-shot
    absence as "the menu does not offer 最多点赞". The fixture reproduces exactly that: same page,
    same mouseover-mounted panel, but 筛选 is buried under a sticky cover. If the dispatch fallback
    is stripped out of ``hover``, the second assertion here goes red.
    """

    def test_a_bare_pointer_move_to_the_centre_does_not_open_it(self, covered_page):
        from selenium.webdriver.common.action_chains import ActionChains

        ActionChains(covered_page).move_to_element(covered_page.find_element('css selector', '#opener')).perform()
        assert menu.nodes_with_text(covered_page, '最新发布') == [], (
            'this fixture is only worth running if the plain pointer really does miss the covered word'
        )

    def test_the_hover_reaches_the_word_anyway_and_choose_then_works(self, covered_page):
        assert menu.hover(covered_page, '筛选') is True, 'the dispatch fallback must open the covered panel'
        assert menu.nodes_with_text(covered_page, '最新发布'), 'hover should have mounted the panel'
        assert menu.option_texts(covered_page, '综合排序') == ['综合排序', '最新发布', '最多点赞']
