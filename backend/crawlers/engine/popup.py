"""Clicking the first-run dialogs that otherwise stall a crawl.

Two measured cases, both costing wall-clock time on every single run:

* **Douyin** puts a ``.trust-login-dialog-mask`` over the page on entry ("是否将
  信息保存到设备"). It is not merely decorative: it *intercepts the click* on the
  search button (``ElementClickInterceptedException`` was observed), and the page
  only drops it after ~5 s. Clicking 是 is therefore both faster and more reliable
  than waiting.
* **Instagram** asks 打开通知 with two buttons, 「打开」 and 「以后再说」 — the
  second is the "no" the user asked for, and it must be the one clicked: 打开
  hands the browser a native permission prompt that has no dismissible DOM.

The table is text-driven on purpose. These dialogs are re-skinned every few
months and the class names churn, but the wording is what the site itself must
keep stable (it is asking the user a question). Matching on the *prompt* text and
choosing among known *button* labels means a re-skin costs a new string here, not
a rewritten crawler — and a dialog that never appeared costs one script call.
"""

import json
import time
from dataclasses import dataclass

# The probe and the click run in one script so a dialog that closes between the
# two round-trips cannot be half-handled.
DISMISS_JS = """
const want = arguments[0];
const done = arguments[arguments.length - 1];
const hit = {clicked: null, matched: null, seen: []};
const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 20 && r.height > 10;
};
const report = () => done(JSON.stringify(hit));
for (const spec of want) {
    let nodes = spec.selector ? [...document.querySelectorAll(spec.selector)] : [];
    if (!nodes.length) nodes = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"]')];
    for (const box of nodes) {
        if (!visible(box)) continue;
        const text = (box.innerText || '').replace(/\\n+/g, ' ');
        if (!text) continue;
        if (!spec.markers.some(m => text.includes(m))) continue;
        hit.matched = text.slice(0, 60);
        hit.seen = [...box.querySelectorAll('button, [role="button"], a, div, span')]
            .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim())
            .filter(t => t && t.length <= 16).slice(0, 12);
        for (const label of spec.choose) {
            if (spec.forbid.includes(label)) continue;
            // div/span are candidates too: douyin's dialog is built out of them,
            // and the exact-text test is what keeps the row that reads
            // 「取消\\n保存」 from being clicked when 「保存」 was asked for.
            for (const b of box.querySelectorAll('button, [role="button"], a, div, span')) {
                const t = (b.innerText || b.getAttribute('aria-label') || '').trim();
                if (t !== label || !visible(b)) continue;
                b.click();
                hit.clicked = label;
                return report();
            }
        }
        return report();
    }
}
report();
"""


@dataclass(frozen=True)
class Prompt:
    """One known interstitial: what identifies it, and which button ends it."""

    key: str
    selector: str
    markers: tuple[str, ...]
    choose: tuple[str, ...]
    forbid: tuple[str, ...] = ()

    def as_js(self) -> dict:
        return {
            'selector': self.selector,
            'markers': list(self.markers),
            'choose': list(self.choose),
            'forbid': list(self.forbid),
        }


#: Douyin's "keep this login" prompt, read off the live DOM: the title is
#: 「是否保存登录信息超过5天」 and the two leaves are 「保存」 and 「取消」.
#: Only 取消 is ever pressed — the user reports that 保存 leads on to a
#: phone-verification step, so declining is both the safer answer and the one that
#: leaves the session alone. The mask is not cosmetic: measured, it intercepts
#: the search button's click (``ElementClickInterceptedException``), and it mounts
#: several seconds *after* the page, which is why the crawler also dismisses on a
#: blocked click rather than only on arrival.
DOUYIN_TRUST_LOGIN = Prompt(
    key='douyin_trust_login',
    selector='.trust-login-dialog-mask',
    markers=('是否保存登录信息', '保存登录信息', '保存到设备', '将信息保存'),
    choose=('取消',),
    forbid=('保存', '是', '同意', '确定'),
)

#: Instagram's notification ask: 「以后再说」 is the "no". 「打开」 is refused
#: because it opens a *browser-level* permission dialog no DOM click can close.
INSTAGRAM_NOTIFICATIONS = Prompt(
    key='instagram_notifications',
    selector='',
    markers=('打开通知', '接收通知', 'Enable notifications', 'Get notifications'),
    choose=('以后再说', '稍后', 'Not Now', 'Not now', 'Later'),
    forbid=('打开', 'Allow', 'Not yet'),
)

#: YouTube's EU consent sheet, seen when the session has no consent cookie. It is
#: harmless to accept and it blocks everything behind it.
YOUTUBE_CONSENT = Prompt(
    key='youtube_consent',
    selector='',
    markers=('Before you continue', '在我们继续之前', '管理设置'),
    choose=('接受全部', '全部接受', 'Accept all'),
    forbid=('拒绝', 'Reject all'),
)

#: How long to look for a dialog before giving up. The first-run prompt mounts
#: with the page, so a crawler that polls for a moment and moves on is strictly
#: better than one that sleeps five seconds on every navigation.
DEFAULT_TRIES = 3
DEFAULT_TICK = 0.35


def dismiss(driver, prompts, tries: int = DEFAULT_TRIES, tick: float = DEFAULT_TICK) -> list:
    """Click through the *prompts* this platform declares; report what happened.

    A platform names its own prompts (``prompts = (DOUYIN_TRUST_LOGIN,)`` on the
    class) rather than this module guessing from a platform key, so adding a
    dialog is a declaration on the one class that can show it.

    Each entry returned is ``{'key', 'clicked', 'matched', 'seen'}`` — the caller
    turns that into console text, because this layer has no business naming a
    node or a platform in the user's language. Never raises: a dialog the site
    stopped showing, or a page whose DOM is mid-re-render, must not cost a crawl.
    """
    specs = tuple(prompts or ())
    out = []
    if not specs:
        return out
    payload = [spec.as_js() for spec in specs]
    keys = [spec.key for spec in specs]
    for attempt in range(max(1, tries)):
        try:
            driver.set_script_timeout(max(5, int(tick * 20)))
            raw = driver.execute_async_script(DISMISS_JS, payload)
        except Exception:
            # A transient renderer state is not a crawl failure; the next
            # navigation gets its own look.
            raw = None
        result = _as_dict(raw)
        index = _spec_that_matched(result, specs)
        if result.get('clicked'):
            out.append(
                {
                    'key': keys[index] if index is not None else '',
                    'clicked': result['clicked'],
                    'matched': result.get('matched') or '',
                    'seen': [],
                }
            )
            return out
        if result.get('matched'):
            # The dialog is on screen and no label of ours matched it: that is a
            # re-skin, and ``seen`` names what the page actually offers so the
            # table above can be updated instead of guessed at.
            out.append(
                {
                    'key': keys[index] if index is not None else '',
                    'clicked': '',
                    'matched': result.get('matched') or '',
                    'seen': result.get('seen') or [],
                }
            )
            return out
        if attempt:
            break  # a second look found nothing either: stop paying ticks
        time.sleep(tick)
    return out


def _spec_that_matched(result: dict, specs) -> int | None:
    """Which prompt the page showed, by matching its text back to the table."""
    matched = str((result or {}).get('matched') or '')
    if not matched:
        return None
    for index, spec in enumerate(specs):
        if any(marker in matched for marker in spec.markers):
            return index
    return None


def _as_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw or '{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
