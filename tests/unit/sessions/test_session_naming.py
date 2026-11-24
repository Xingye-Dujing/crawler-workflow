"""The foldings a (platform, account) pair has: one name, one file, one device directory.

Each case is a rule that once lived inside ``sessions.cookies``/``sessions.profiles`` and is now
a pure function, so it can be asked without a cookie directory, a browser or a settings file.
"""

import os

import pytest
from sessions import naming

pytestmark = pytest.mark.unit


@pytest.mark.parametrize('account', ['', None, '   ', 'default', 'DEFAULT', ' Default '])
def test_the_platforms_own_login_is_one_name_under_every_spelling(account):
    assert naming.account_name(account) == naming.DEFAULT_ACCOUNT
    assert naming.account_segment(account) == ''
    assert naming.is_default(account) is True


@pytest.mark.parametrize('account', ['work', ' Work ', 'WORK'])
def test_a_named_account_is_lowercased_and_keeps_its_saying(account):
    assert naming.account_name(account) == 'work'
    assert naming.account_segment(account) == 'work'
    assert naming.is_default(account) is False


class TestTheAccountLabelRule:
    @pytest.mark.parametrize('account', ['', 'default', 'a', 'work', 'work_2', 'a-b', 'x' * 24])
    def test_a_label_the_jar_accepts(self, account):
        assert naming.is_account_label(account) is True

    @pytest.mark.parametrize('account', ['a.b', 'a/b', 'a\\b', 'a@b', 'a b', 'x' * 25, '中文'])
    def test_a_label_that_would_be_a_path_or_a_second_account(self, account):
        assert naming.is_account_label(account) is False


class TestTheCookieFileName:
    def test_the_default_login_keeps_the_historical_unsuffixed_name(self):
        assert naming.cookie_filename('zhihu') == 'zhihu_cookies.json'
        assert naming.cookie_filename('zhihu', 'default') == 'zhihu_cookies.json'
        assert naming.cookie_filename('zhihu', '') == 'zhihu_cookies.json'

    def test_a_named_login_nests_under_the_platform(self):
        assert naming.cookie_filename('weibo', 'Work') == 'weibo@work_cookies.json'


class TestTheProfileDirectory:
    def test_the_default_device_is_the_platform_directory(self, tmp_path):
        root = str(tmp_path / 'profiles')
        assert naming.profile_path(root, 'zhihu') == os.path.join(root, 'zhihu')
        assert naming.profile_path(root, 'zhihu', 'default') == os.path.join(root, 'zhihu')

    def test_a_named_account_nests_one_level(self, tmp_path):
        root = str(tmp_path / 'profiles')
        assert naming.profile_path(root, 'weibo', 'work') == os.path.join(root, 'weibo', 'work')

    @pytest.mark.parametrize('account', ['..', 'work.home', 'x/../../y', '中文'])
    def test_a_label_that_is_not_a_safe_directory_is_refused(self, account):
        with pytest.raises(ValueError, match='Invalid account'):
            naming.profile_segment(account)


class TestChronologicalAccountOrder:
    def test_the_oldest_save_comes_first_not_the_alphabetical_one(self):
        born = {'alice': 20.0, 'bob': 10.0}
        assert naming.account_order(['alice', 'bob'], born) == ['bob', 'alice']

    def test_a_file_whose_creation_time_could_not_be_read_sorts_last(self):
        assert naming.account_order(['a', 'b', 'c'], {'c': 5.0}) == ['c', 'a', 'b']

    def test_a_tie_is_broken_by_the_label_so_the_order_is_stable(self):
        assert naming.account_order(['b', 'a'], {'a': 1.0, 'b': 1.0}) == ['a', 'b']


class TestTheNextFreeDefaultLabel:
    def test_an_empty_platform_keeps_the_name_of_its_slot(self):
        assert naming.next_free_label([]) == 'default'

    def test_a_taken_default_is_numbered_from_two(self):
        assert naming.next_free_label(['default']) == 'default2'
        assert naming.next_free_label(['default', 'work']) == 'default2'

    def test_the_first_gap_is_used_even_when_a_higher_number_is_taken(self):
        assert naming.next_free_label(['default', 'default3']) == 'default2'

    def test_a_named_account_alone_leaves_the_default_free(self):
        assert naming.next_free_label(['work']) == 'default'
