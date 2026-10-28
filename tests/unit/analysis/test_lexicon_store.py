"""The lexicon store and how the analysis pipeline reads it.

Two properties carry the feature: a user stop word actually removes a token from every
frequency table (through the one choke point), and the jieba domain terms materialise to the
dictionary file the tokenizer loads. Both must degrade to "no user list" rather than raise —
a broken or empty lexicon can never take down a run.
"""

import os

import jieba
import pytest
import stores

from analyzers import stopwords
from services.analysis import lexicon as lexicon_service
from services.analysis.lexicon import materialize_userdict, reload_userdict, userdict_path
from services.analysis.lexicon_store import LexiconStore


def _store(tmp_path):
    store = LexiconStore(str(tmp_path / 'lexicon.db'))
    stores._LEXICON_STORE = store
    # Force the analyzer cache to reload against this store, not a prior test's.
    stopwords._USER_STOP = {'version': None, 'set': frozenset()}
    return store


class TestStore:
    def test_add_dedupes_within_and_across(self, tmp_path):
        store = _store(tmp_path)
        result = store.add('stopword', ['哈哈', '哈哈', '  ', '么么哒'])
        assert result == {'added': 2, 'skipped': 0}
        assert set(store.terms('stopword')) == {'哈哈', '么么哒'}

    def test_version_bumps_only_on_a_real_change(self, tmp_path):
        store = _store(tmp_path)
        v0 = store.version()
        store.add('stopword', ['新词'])
        assert store.version() == v0 + 1
        store.add('stopword', ['新词'])  # duplicate → no change
        assert store.version() == v0 + 1

    def test_remove_and_clear(self, tmp_path):
        store = _store(tmp_path)
        store.add('stopword', ['a词', 'b词'])
        assert store.remove('stopword', 'a词') == 1
        assert store.terms('stopword') == ['b词']
        assert store.clear('stopword') == 1
        assert store.counts() == {'stopword': 0, 'userdict': 0}

    def test_userdict_keeps_a_trailing_frequency(self, tmp_path):
        store = _store(tmp_path)
        store.add('userdict', ['绝绝子 200', '超话'])
        rows = {r['term']: r['weight'] for r in store.list('userdict')}
        assert rows == {'绝绝子': 200, '超话': None}

    def test_an_unknown_kind_is_refused(self, tmp_path):
        store = _store(tmp_path)
        try:
            store.add('nonsense', ['x'])
        except ValueError:
            return
        raise AssertionError('add() must refuse an unknown kind')


class TestStopwordWiring:
    def test_a_user_stopword_is_filtered_and_removing_restores_it(self, tmp_path):
        store = _store(tmp_path)
        assert stopwords.is_meaningful('哈哈') is True
        store.add('stopword', ['哈哈'])
        assert stopwords.is_meaningful('哈哈') is False
        store.remove('stopword', '哈哈')
        assert stopwords.is_meaningful('哈哈') is True

    def test_a_broken_store_falls_back_to_the_builtin_list(self, tmp_path):
        stores._LEXICON_STORE = None
        stopwords._USER_STOP = {'version': None, 'set': frozenset()}
        # Even with no store wired, the built-in filter still works and nothing raises.
        assert stopwords.is_meaningful('的') is False
        assert stopwords.is_meaningful('哈哈') is True


class TestUserdictFile:
    def test_empty_lexicon_writes_no_file(self, tmp_path):
        _store(tmp_path)
        # The dict file lives under the session-wide data root, not this test's tmp;
        # clear any leftover so "nothing to write" is measured from a clean slate.
        if os.path.isfile(userdict_path()):
            os.remove(userdict_path())
        assert materialize_userdict() == 0
        assert not os.path.isfile(userdict_path()), 'an empty dict must not touch data/'

    def test_terms_are_written_in_jieba_format(self, tmp_path):
        store = _store(tmp_path)
        store.add('userdict', ['绝绝子 200', '超话'])
        assert materialize_userdict() == 2
        with open(userdict_path(), encoding='utf-8') as handle:
            content = handle.read()
        assert '绝绝子 200' in content
        assert '超话' in content


class TestLiveReloadWithdrawsDeletedTerms:
    """``jieba.load_userdict`` only ADDS. The module promises a panel edit is live for the next
    run without a restart, and while the reload was additive a DELETED term stayed glued into
    every segmentation until the process restarted — the opposite of the edit the user made."""

    WORD = '啉嘟噜啦'
    OTHER = '啦噜嘟啉'

    @pytest.fixture
    def lex(self, tmp_path):
        store = _store(tmp_path)
        if os.path.isfile(userdict_path()):
            os.remove(userdict_path())
        # jieba's dictionary is one process-wide object: forget what an earlier test loaded,
        # so this test withdraws only its own words.
        lexicon_service._loaded_terms = set()
        yield store
        lexicon_service._loaded_terms = set()

    def test_an_added_term_is_one_token(self, lex):
        lex.add('userdict', [self.WORD])
        assert self.WORD not in jieba.lcut(self.WORD), 'the premise: the built-in dict splits it'
        reload_userdict()
        assert self.WORD in jieba.lcut(self.WORD), 'the panel added a domain term and nothing glued it'

    def test_a_deleted_term_is_taken_back_out_of_the_tokenizer(self, lex):
        lex.add('userdict', [self.WORD, self.OTHER])
        reload_userdict()
        assert self.WORD in jieba.lcut(self.WORD)
        lex.remove('userdict', self.WORD)
        reload_userdict()
        assert self.WORD not in jieba.lcut(self.WORD), 'a deleted term survived the reload'
        # …while the term that was NOT deleted stays, or the fix would be a blanket reset that
        # silently throws away the rest of the lexicon.
        assert self.OTHER in jieba.lcut(self.OTHER), 'the reload withdrew more than was deleted'
