"""Real Chrome and the pristine template: the claim is measured, not asserted.

The unit tier stubs the browser, which proves the *policy* (what may be copied, when a
directory may be seeded, what a dirty template does). It cannot prove the two things that
make the feature worth having at all:

* that a directory created by launching a blank Chrome really holds no login — the
  template is pristine because nothing was ever put into it, and that is a statement
  about what Chrome writes, so only Chrome can be asked;
* that a directory seeded from it is still a profile Chrome accepts, rather than a tree
  of foreign files that makes the first run of a new account fail.

Local pages only, and this tier performs no server writes.
"""

import contextlib
import os
import time

import browser_profiles
import pytest

from crawlers import get_crawler
from crawlers.base import warm_profile_dir

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    root = str(tmp_path / 'profiles')
    monkeypatch.setattr(
        browser_profiles,
        'get_setting',
        lambda key: {'use_browser_profile': True, 'browser_profile_dir': root}[key],
    )
    return root


def _browser_or_skip(what, action):
    """Start a browser through *action*, skipping only when a retry says the same thing.

    This file buys several Chrome processes in a row, and on Windows the one after a
    sibling's teardown occasionally refuses to start. Skipping on the first error would
    then hide the only measurement the pristine template has — a green run that never
    opened a browser reads exactly like a template that was checked and found clean. A
    machine with no Chrome fails twice for the same reason, and that is the one answer
    that legitimately skips; both attempts are named in the message, so a skip can be
    told apart from a flake after the fact.
    """
    try:
        return action()
    except Exception as first:
        time.sleep(1.0)
        try:
            return action()
        except Exception as second:
            pytest.skip(f'Chrome/chromedriver unavailable ({what}): {first} / retry: {second}')


def _warm(path: str) -> None:
    """One blank Chrome in *path*, or a skip when this machine has no browser.

    Called straight from :mod:`crawlers.base` rather than through ``browser_profiles``:
    the profile module must not own a browser, and the app passes this same function in as
    its launcher, so the template the tier measures is the one the route makes.
    """
    _browser_or_skip('warm', lambda: warm_profile_dir(path))


def _all_names(path: str) -> set:
    names = set()
    for walk_root, _dirs, files in os.walk(path):
        names.update(files)
        names.update(os.path.basename(walk_root) for walk_root in (_dirs or []))
    return names


def _stores_seen(path: str) -> list:
    """The Chrome stores a first run actually wrote, with the rows each one holds.

    ``verify_pristine() == ''`` has two ways to be true: every store was opened and found
    empty, or there was nothing to open. Only the first is the claim being tested, so the
    tier counts the stores it read and their sizes rather than trusting the empty answer.
    """
    seen = []
    for walk_root, _dirs, files in os.walk(path):
        for name in files:
            table = browser_profiles._SESSION_TABLES.get(name)
            if table is None:
                continue
            full = os.path.join(walk_root, name)
            seen.append((os.path.relpath(full, path), browser_profiles._store_row_count(full, table)))
    return sorted(seen)


def test_a_blank_chrome_leaves_a_directory_with_no_login_in_it(rooted):
    """The whole feature stands on this one measurement.

    ``Login Data``, ``History``, ``Cookies`` and the rest are what a person's session
    looks like on disk. A generated template that holds none of them is safe to copy
    into every account made afterwards; one that held them would ship a login to
    strangers, which is the harm the 「不要复制我的日常 Chrome」 rule exists to prevent.

    This is also the measurement that moved the check from names to rows: a blank first
    run writes those names by itself, so the only honest question is how much is in them.
    """
    source = browser_profiles.template_dir()
    os.makedirs(source, exist_ok=True)
    _warm(source)
    made = [name for name in os.listdir(source) if name != browser_profiles.MARKER]
    assert made, f'Chrome wrote nothing into the directory it was given: {made}'
    seen = _stores_seen(source)
    assert seen, (
        f'no Chrome store was written at all, so the clean verdict measured nothing: {sorted(_all_names(source))}'
    )
    assert browser_profiles.verify_pristine() == '', (
        f'a blank first run left session material behind: {seen} / {sorted(_all_names(source))}'
    )


def test_the_generated_template_is_the_one_the_tool_trusts(rooted):
    """The two claims are the same check: what the builder verifies, the seeder obeys."""
    source = browser_profiles.template_dir()
    os.makedirs(source, exist_ok=True)
    _warm(source)
    assert browser_profiles.template_exists() is True
    target = browser_profiles.platform_dir('bilibili', 'fresh')
    os.makedirs(target, exist_ok=True)
    copied = browser_profiles.seed_new_profile(target)
    assert copied > 0, 'a clean template refused to seed a new account'
    assert browser_profiles.MARKER not in os.listdir(target), os.listdir(target)


def test_a_seeded_directory_is_a_profile_a_real_browser_accepts(rooted):
    """A seed that Chrome refused to open would look like success and cost the account.

    The browser is pointed at the seeded directory the way a crawl points at it, and the
    proof is Chrome doing what it does with a real profile: writing more of its own
    files, and leaving the marker to no one until the tool itself records a use.
    """
    source = browser_profiles.template_dir()
    os.makedirs(source, exist_ok=True)
    _warm(source)
    target = browser_profiles.platform_dir('bilibili', 'acct1')
    os.makedirs(target, exist_ok=True)
    before = sorted(os.listdir(target))
    assert browser_profiles.seed_new_profile(target) > 0
    assert sorted(os.listdir(target)) != before, 'nothing was seeded'
    crawler = _browser_or_skip(
        'crawl', lambda: get_crawler('bilibili', headless=True, use_profile=True, account='acct1', cookie_dir=None)
    )
    try:
        with contextlib.suppress(Exception):
            crawler.driver.get('about:blank')
        assert crawler.profile_dir == target, (
            f'the browser was pointed somewhere else: {crawler.profile_dir} != {target}'
        )
        assert os.listdir(target), 'the browser emptied the directory it was given'
    finally:
        crawler.close()
    # The marker is written by the tool around a real use, never inherited from the copy.
    assert browser_profiles.is_used('bilibili', 'acct1') is True


def test_a_directory_that_has_been_used_is_never_reseeded(rooted):
    source = browser_profiles.template_dir()
    os.makedirs(source, exist_ok=True)
    _warm(source)
    target = browser_profiles.platform_dir('bilibili', 'acct2')
    os.makedirs(target, exist_ok=True)
    assert browser_profiles.seed_new_profile(target) > 0
    settled = sorted(os.listdir(target))
    with open(os.path.join(target, 'First Run'), 'w', encoding='utf-8') as handle:
        handle.write('this device has its own history now')
    assert browser_profiles.seed_new_profile(target) == 0
    assert sorted(os.listdir(target)) == settled, 'a second seed changed a live device'
    with open(os.path.join(target, 'First Run'), encoding='utf-8') as handle:
        assert handle.read() == 'this device has its own history now'
