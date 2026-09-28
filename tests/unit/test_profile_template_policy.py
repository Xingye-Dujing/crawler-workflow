"""The pristine profile template: what it is allowed to contain, and where it may go.

A cloud host has no 「浏览器生成」 button, so a device directory has to be made by the
program. That is only safe while two things hold, and this file is the check on both:

* the template holds **no session** — it is pristine because nothing was ever logged into
  it, and a template that stopped being pristine must be rebuilt rather than copied;
* copying it never carries a login, a history entry, a machine key or **our own marker**
  into a new account directory (a seeded ``.crawler-profile.json`` would tell the
  import-once rule that the account already has a session, and the cookie the user just
  pasted would never be planted).

No Chrome is started here: :func:`build_template` takes the browser as an argument, which
is the same seam ``test_cookie_save_plants_profile`` uses for the save path.
"""

import json
import os
import threading
import time

import browser_profiles
import pytest

pytestmark = pytest.mark.unit

#: A first-run directory's worth of names, chosen for the one property that matters: the
#: safe ones are what Chrome makes before anyone signs in, the unsafe ones are where a
#: login lives or a machine key is wrapped. ``Local State`` is deliberately on the unsafe
#: side: it is not a session, but it is this machine's key material and Chrome rebuilds it.
SAFE_ENTRIES = ['First Run', 'Last Version', 'Variations', 'DevToolsActivePort']
UNSAFE_ENTRIES = ['Login Data', 'History', 'Web Data', 'Cookies', 'Preferences', 'Local State']


@pytest.fixture
def rooted(monkeypatch, tmp_path):
    """Point the whole profile root at a throwaway directory."""
    values = {'use_browser_profile': True, 'browser_profile_dir': str(tmp_path / 'profiles')}
    monkeypatch.setattr(browser_profiles, 'get_setting', lambda key: values[key])
    return tmp_path / 'profiles'


def _touch(path: str, text: str = 'x') -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path


def _make_store(path: str, table: str, rows: int = 0) -> str:
    """A real Chrome-shaped SQLite store, with the number of rows the case is about.

    A file name proves nothing here (a blank first run of Chrome creates ``Cookies``,
    ``Login Data`` and ``History`` empty), so the fixtures have to be readable databases
    — otherwise every "dirty template" case below would be a clean one by accident, and
    the check would be measured against a strawman.
    """
    import sqlite3

    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (id INTEGER PRIMARY KEY, blob TEXT)')
        db.executemany(f'INSERT INTO "{table}" (blob) VALUES (?)', [(f'row{i}',) for i in range(rows)])
        db.commit()
    finally:
        # A fixture that holds the file open cannot be deleted, and the dirty-template cases
        # ask the product to delete exactly the directory the fixture just wrote.
        db.close()
    return path


def _make_template(rooted, *, safe=SAFE_ENTRIES, unsafe=(), nested=(), stores=(), origins=()) -> str:
    """Lay a template directory out on disk.

    ``unsafe`` are names the copy must refuse (whatever they contain); ``stores`` are
    ``(relative path, table, rows)`` triples of real SQLite stores, which is the only way
    to express "this template has somebody's login in it"; ``origins`` are
    ``Default/IndexedDB`` sub-directories, which a blank run never makes.
    """
    source = browser_profiles.template_dir()
    os.makedirs(source, exist_ok=True)
    for name in safe:
        _touch(os.path.join(source, name))
    for name in unsafe:
        _touch(os.path.join(source, name))
    for name in nested:
        _touch(os.path.join(source, name))
    for rel, table, rows in stores:
        _make_store(os.path.join(source, rel), table, rows)
    for origin in origins:
        os.makedirs(os.path.join(source, 'Default', 'IndexedDB', origin), exist_ok=True)
    return source


class TestBuildingIt:
    def test_the_launcher_is_what_creates_it_and_the_result_says_so(self, rooted):
        seen = []

        def launch(path):
            seen.append(path)
            _touch(os.path.join(path, 'First Run'))

        result = browser_profiles.build_template(launch=launch)
        assert result == {'ok': True, 'built': True, 'path': str(rooted / '_template')}, result
        assert seen == [str(rooted / '_template')], 'the launcher was not pointed at the template dir'

    def test_a_machine_with_no_browser_reports_rather_than_raising(self, rooted):
        """The caller is a web request; "there is no chromedriver here" is its answer."""

        def broken(path):
            raise RuntimeError('chromedriver not found')

        result = browser_profiles.build_template(launch=broken)
        assert result['ok'] is False and 'chromedriver' in result['reason'], result

    def test_without_a_launcher_nothing_is_claimed(self, rooted):
        assert browser_profiles.build_template() == {'ok': False, 'built': False, 'reason': 'no-launcher'}
        assert not browser_profiles.template_exists(), 'a build that did not happen left no directory'

    def test_a_dirty_template_is_destroyed_before_the_new_one_is_built(self, rooted):
        """The point of generating it is that nobody ever logged into it."""
        source = _make_template(rooted, stores=[('Default/Login Data', 'logins', 2)])
        launched = []

        def launch(path):
            launched.append(path)
            assert os.listdir(path) == [], f'the dirty directory survived: {os.listdir(path)}'
            _touch(os.path.join(path, 'First Run'))

        result = browser_profiles.build_template(launch=launch)
        assert result['ok'] is True, result
        assert launched == [source]
        assert browser_profiles.verify_pristine() == ''

    def test_a_launch_that_leaves_a_session_behind_is_reported_not_shipped(self, rooted):
        """Chrome will not do that today; the check is why the claim stays true."""

        def launch(path):
            _make_store(os.path.join(path, 'Default', 'Login Data'), 'logins', 1)

        result = browser_profiles.build_template(launch=launch)
        assert result['ok'] is False and 'not-pristine' in result['reason'], result


class TestWhatIsPristine:
    def test_an_empty_directory_is_pristine(self, rooted):
        os.makedirs(browser_profiles.template_dir(), exist_ok=True)
        assert browser_profiles.verify_pristine() == ''

    def test_a_store_is_judged_by_what_is_in_it_not_by_its_name(self, rooted):
        """The distinction the whole check rests on, in one case.

        A blank first run of Chrome creates ``Cookies``, ``Login Data`` and ``History``
        with zero rows in them (measured in the device tier), so a name-based verdict
        would call every real template dirty and seed nothing ever. The rows are the
        difference between Chrome's own scaffolding and somebody's login.
        """
        _make_template(
            rooted,
            stores=[
                ('Default/Network/Cookies', 'cookies', 0),
                ('Default/Login Data', 'logins', 0),
                ('Default/History', 'visits', 0),
            ],
        )
        assert browser_profiles.verify_pristine() == '', browser_profiles.find_session_material()

    def test_a_filled_store_anywhere_in_the_tree_is_found(self, rooted):
        """A listing of the top level proves nothing: the cookie store is two levels down."""
        _make_template(
            rooted,
            stores=[('Default/Network/Cookies', 'cookies', 4), ('Default/Login Data', 'logins', 1)],
        )
        found = browser_profiles.verify_pristine()
        assert 'Cookies (4 rows)' in found, found
        assert 'Login Data (1 rows)' in found, found

    def test_an_indexeddb_origin_is_material_though_no_store_here_lists_it(self, rooted):
        """A site that kept anything on disk leaves a directory named after itself.

        Chrome's local-storage and IndexedDB trees are not SQLite, so no row count reaches
        them — and an origin directory is exactly what "this device has been used to
        browse" looks like there. A blank run creates none, which is what makes its
        absence a usable answer.
        """
        _make_template(rooted, origins=['https_weibo.com_0.indexeddb.leveldb'])
        assert 'IndexedDB' in browser_profiles.verify_pristine().replace('\\', '/'), (
            browser_profiles.find_session_material()
        )

    def test_a_safe_first_run_tree_passes(self, rooted):
        _make_template(rooted, nested=['Default/Cache/index', 'Default/DawnGraphiteCache/data_0'])
        assert browser_profiles.verify_pristine() == '', browser_profiles.find_session_material()

    def test_preferences_is_never_copied_though_it_is_not_a_login(self, rooted):
        """Two different rules, and it is worth keeping them straight.

        ``Default/Preferences`` holds restored tabs and per-site content settings — not a
        credential, so the pristine check does not flag it. It is still refused by the
        copy, because a new account that inherits someone's window state is a worse
        device, not a leaked one.
        """
        _make_template(rooted, nested=['Default/Preferences'])
        assert browser_profiles.verify_pristine() == ''
        assert browser_profiles._is_unsafe('Preferences') is True


class TestSeeding:
    def test_only_the_safe_half_of_a_tree_crosses_the_copy(self, rooted):
        """The filter is the copy's own rule, tested where it lives.

        :func:`seed_new_profile` refuses a dirty template before copying anything, so
        going through it would only ever test the refusal; the exclusion list is what
        keeps a leaked-in store from spreading even when the template looked clean at the
        names this walk checks.
        """
        source = _make_template(
            rooted,
            unsafe=UNSAFE_ENTRIES,
            nested=[
                'Default/Login Data',
                'Default/Network/Cookies',
                'Default/Local Storage/leveldb/000003.log',
                'Default/Session Storage/LOG',
                'Crashpad/reports/dump',
                'SingletonLock',
            ],
        )
        target = os.path.join(str(rooted), 'zhihu', 'work')
        os.makedirs(target, exist_ok=True)
        assert browser_profiles._copy_template_into(source, target) > 0
        landed = set(os.listdir(target))
        assert landed == set(SAFE_ENTRIES), landed
        for walk_root, dirs, files in os.walk(target):
            for name in (*dirs, *files):
                assert name not in ('Cookies', 'Login Data', 'History', 'Web Data', 'Preferences', 'dump'), (
                    os.path.relpath(os.path.join(walk_root, name), target)
                )
        assert not os.path.isdir(os.path.join(target, 'Default', 'Network')), 'the cookie store came along'

    def test_a_name_the_copy_refuses_does_not_have_to_be_a_login(self, rooted):
        """The copy's list and the content check answer different questions.

        ``Local State`` holds the machine's encryption key material and is therefore never
        copied, while naming it would tell nobody whether a login is in the directory.
        Both rules are wanted; conflating them is how a check starts passing on empty files
        that a real Chrome writes anyway.
        """
        _make_template(rooted, unsafe=['Local State'])
        assert browser_profiles._is_unsafe('Local State') is True
        assert browser_profiles.verify_pristine() == ''

    def test_our_own_marker_is_never_copied(self, rooted):
        """A seeded marker would claim a session the new account never had.

        ``is_used`` reads it, the import-once rule obeys ``is_used``, and the paste the
        user just made would be judged "already inside that profile" — a cookie silently
        missing on the one machine where nobody can open a window to fix it.
        """
        source = _make_template(rooted)
        _touch(os.path.join(source, browser_profiles.MARKER), '{"used_at": "2026-09-28 10:00:00"}')
        target = os.path.join(str(rooted), 'weibo')
        os.makedirs(target, exist_ok=True)
        browser_profiles.seed_new_profile(target)
        assert browser_profiles.MARKER not in os.listdir(target), os.listdir(target)
        assert browser_profiles.is_used('weibo') is False

    def test_a_directory_that_is_not_empty_is_left_alone(self, rooted):
        """Someone else's Chrome may already be writing there."""
        _make_template(rooted)
        target = os.path.join(str(rooted), 'douyin')
        _touch(os.path.join(target, 'already-here'))
        assert browser_profiles.seed_new_profile(target) == 0
        assert os.listdir(target) == ['already-here']

    def test_no_template_answers_zero_rather_than_inventing_one(self, rooted):
        target = os.path.join(str(rooted), 'bilibili')
        os.makedirs(target, exist_ok=True)
        assert browser_profiles.seed_new_profile(target) == 0

    def test_a_dirty_template_seeds_nothing_at_all(self, rooted):
        _make_template(rooted, stores=[('Login Data', 'logins', 1)])
        target = os.path.join(str(rooted), 'zhihu')
        os.makedirs(target, exist_ok=True)
        assert browser_profiles.seed_new_profile(target) == 0
        assert os.listdir(target) == []

    def test_the_template_never_seeds_itself(self, rooted):
        """Copying a directory into itself would either no-op or eat it."""
        source = _make_template(rooted)
        assert browser_profiles.seed_new_profile(source) == 0
        assert sorted(os.listdir(source)) == sorted(SAFE_ENTRIES), os.listdir(source)


class TestFirstCreationOnly:
    def test_creating_an_account_profile_seeds_it_once(self, rooted, monkeypatch):
        """The second caller must not re-copy over a directory the first one is using.

        ``os.makedirs(exist_ok=True)`` cannot tell "I made this" from "this was here", so
        the real code asks ``exist_ok=False`` and catches the answer; this drives two
        creations of the same brand-new directory and counts the copies.
        """
        _make_template(rooted)
        calls = []
        real = browser_profiles._copy_template_into

        def counting(source, target):
            calls.append(target)
            time.sleep(0.05)  # widen the window the race would slip through
            return real(source, target)

        monkeypatch.setattr(browser_profiles, '_copy_template_into', counting)
        threads = [
            threading.Thread(target=lambda: browser_profiles.profile_dir_for('zhihu', account='work')) for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert len(calls) == 1, f'{len(calls)} threads seeded the same directory'
        path = browser_profiles.platform_dir('zhihu', 'work')
        assert 'First Run' in os.listdir(path), os.listdir(path)

    def test_an_existing_profile_is_not_reseeded_and_its_files_survive(self, rooted):
        browser_profiles.profile_dir_for('zhihu', account='work')
        _make_template(rooted)  # the template appears AFTER the account existed
        path = browser_profiles.platform_dir('zhihu', 'work')
        _touch(os.path.join(path, 'mine'))
        browser_profiles.profile_dir_for('zhihu', account='work')
        assert 'mine' in os.listdir(path), 'a later call overwrote a live device'
        assert 'First Run' not in os.listdir(path), os.listdir(path)

    def test_profiles_off_still_creates_nothing(self, rooted, monkeypatch):
        monkeypatch.setattr(browser_profiles, 'is_enabled', lambda: False)
        assert browser_profiles.profile_dir_for('zhihu') is None
        assert not os.path.isdir(browser_profiles.platform_dir('zhihu'))


class TestTheReservedName:
    def test_a_platform_cannot_be_called_the_template(self, rooted):
        """``<root>/_template`` is the template; a platform of that name would alias it."""
        with pytest.raises(ValueError, match='Reserved'):
            browser_profiles.platform_dir('_template')
        # And the account form still works, because an account nests under its platform.
        assert browser_profiles.platform_dir('zhihu', '_template').endswith(os.path.join('zhihu', '_template'))

    def test_a_bad_account_label_never_reaches_a_path(self, rooted):
        for bad in ('..', '../escape', 'A B', 'x' * 30):
            with pytest.raises(ValueError):
                browser_profiles.platform_dir('zhihu', bad)


class TestStatusAnswers:
    def test_the_row_reports_the_two_states_apart(self, rooted):
        assert browser_profiles.template_exists() is False
        assert browser_profiles.find_session_material() == []
        _make_template(rooted, stores=[('Default/History', 'visits', 2)])
        assert browser_profiles.template_exists() is True
        found = browser_profiles.find_session_material()
        assert [os.path.normpath(hit.split(' (')[0]) for hit in found] == [os.path.join('Default', 'History')], found
        # Where it is and how much is in it, because 「模板脏了」 alone tells nobody what to do.
        assert '2 rows' in found[0], found

    def test_a_marker_written_by_the_tool_is_not_a_session(self, rooted):
        """The marker is ours and it says "this device was used"; it is not a login.

        It has to stay out of the pristine verdict, or the first account that logs in
        would make the template unusable by the check meant to protect it.
        """
        source = _make_template(rooted)
        with open(os.path.join(source, browser_profiles.MARKER), 'w', encoding='utf-8') as handle:
            json.dump({'used_at': '2026-09-28 10:00:00', 'imported_at': '', 'cookie_stamp': ''}, handle)
        assert browser_profiles.verify_pristine() == ''
