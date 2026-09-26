"""Opening the hover menus a result page hides behind one corner word.

Measured on douyin's search results (``docs/crawler_notes.md``, 2026-09-26): the sort choices
(综合排序 / 最新发布 / 最多点赞) and the 发布时间 / 视频时长 / 观看状态 groups all live in a panel
that appears **only while the pointer is on 「筛选」** — clicking that word closes it again — and
choosing an item leaves the address exactly as it was (``/search/IU?type=video`` before, the same
after). Two consequences this module exists to enforce:

* the sequence is *hover → read → pick*, and every pick needs its own hover: a chosen item closes
  the panel and the stale handle answers the next pick with silence, which reads as "the order did
  not change" rather than as "I never asked";
* because no URL carries the choice, **the crawler is the only record of which order it crawled**.
  So a pick that cannot be made is refused by name instead of quietly continuing on the default
  order, and the chosen value belongs in the resume cursor beside it.

The site's own words are the selectors on purpose. The class names beside them are build hashes
(``eXMmo3JR`` was current today, and it will not be in a month), which is the same reason
:mod:`crawlers.engine.popup` matches dialog text instead of structure: a re-skin costs a new
string here, not a rewritten crawler.
"""

import contextlib
import time

#: An element whose *own* text node is the word — what a tab or a menu item is. Matching with
#: ``contains`` instead would land on the section that holds the whole list.
TEXT_XPATH = "//*[normalize-space(text())='%s']"

#: Put the pointer's logical "arrive" onto the node itself, whatever sits on top of its centre.
#: The events a hover-wired panel listens for; the geometry-independent way to reach the word when
#: ``ActionChains`` aims at a centre a sticky header covers (see :func:`hover`).
_ENTER_JS = """
const el = arguments[0];
const fire = (type, Ctor) =>
    el.dispatchEvent(new Ctor(type, {bubbles: true, cancelable: true, view: window}));
fire('pointerover', PointerEvent);
fire('pointerenter', PointerEvent);
fire('mouseover', MouseEvent);
fire('mouseenter', MouseEvent);
fire('mousemove', MouseEvent);
"""


def nodes_with_text(driver, text: str) -> list:
    """Every element currently on the page that calls itself *text*."""
    return driver.find_elements('xpath', TEXT_XPATH % text)


def hover(driver, text: str, settle: float = 1.2) -> bool:
    """Put the pointer on *text* and give the panel time to mount. False if there is no such word.

    ``ActionChains.move_to_element`` aims at the element's geometric centre, and a sticky header can
    cover that centre under a headless layout — measured on douyin's live result page (2026-09-26):
    the hover returned True but the panel never mounted, because the pointer landed on the header,
    not on 筛选. So the enter events are also dispatched straight onto the node, which is
    geometry-independent and opens the same panel in both shapes. The pointer move is kept first as
    the trusted-event path a visible window already relies on; either step is best-effort, so a page
    is only reported as having no opener when the word itself is absent.
    """
    from selenium.webdriver.common.action_chains import ActionChains

    nodes = nodes_with_text(driver, text)
    if not nodes:
        return False
    node = nodes[0]
    with contextlib.suppress(Exception):
        ActionChains(driver).move_to_element(node).perform()
    with contextlib.suppress(Exception):
        driver.execute_script(_ENTER_JS, node)
    time.sleep(settle)
    return True


def pick(driver, text: str) -> bool:
    """Click the element named *text*. The panel must already be open (see :func:`hover`)."""
    for node in nodes_with_text(driver, text):
        try:
            node.click()
            return True
        except Exception:
            continue
    return False


def option_texts(driver, anchor_text: str) -> list:
    """The words sharing *anchor_text*'s own class — the honest way to read one menu's items.

    A menu's items are siblings that carry the same (hashed) class, so the row is enumerated from
    an item we can see instead of from a container selector someone guessed.
    """
    nodes = nodes_with_text(driver, anchor_text)
    if not nodes:
        return []
    classes = (nodes[0].get_attribute('class') or '').split()
    if not classes:
        return []
    out = []
    for element in driver.find_elements('xpath', f"//*[contains(@class,'{classes[0]}')]"):
        text = (element.text or '').strip()
        if text and text not in out:
            out.append(text)
    return out


def choose(
    driver,
    opener_text: str,
    option_text: str,
    snapshot,
    timeout: float = 15.0,
    poll: float = 1.0,
    sample_text: str = '',
) -> dict:
    """Open the menu, pick *option_text*, and wait until the page says something different.

    *snapshot* is a zero-argument call returning something comparable — the ids on screen, a row
    count, whatever the caller can prove the choice must move. ``changed=False`` with
    ``ok=True`` is a real answer, not a failure: picking the value that is already in force
    changes nothing, and douyin's 不限 was measured doing exactly that.

    *sample_text* names a word the caller **knows the menu offers**, used only to enumerate the
    alternatives when the wanted one is absent — reporting "not found" with an empty list is a
    dead end, while listing what the menu does hold tells the reader the site renamed the choice.

    The refusal names what could not be done (``no_opener`` / ``missing`` / ``no_handle``), because
    "the control is gone", "the word changed" and "it would not click" are three different repairs.
    """
    if not hover(driver, opener_text):
        return {'ok': False, 'reason': 'no_opener', 'changed': False}
    before = snapshot()
    if not nodes_with_text(driver, option_text):
        return {
            'ok': False,
            'reason': 'missing',
            'changed': False,
            'options': option_texts(driver, sample_text or option_text),
        }
    if not pick(driver, option_text):
        return {'ok': False, 'reason': 'no_handle', 'changed': False}
    deadline = time.time() + timeout
    changed = False
    while time.time() < deadline:
        if snapshot() != before:
            changed = True
            break
        time.sleep(poll)
    return {'ok': True, 'reason': '', 'changed': changed}
