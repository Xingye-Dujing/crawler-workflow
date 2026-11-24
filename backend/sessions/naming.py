"""The two names one account has on disk: its cookie file and its Chrome profile.

One login is one (platform, account) pair, and that pair is spelled three ways:

* the **name** (``default``) — what a list, a label and a node parameter carry;
* the **file segment** (``''`` for the default) — the historical unsuffixed cookie filename,
  kept byte-for-byte so a workflow saved before multi-account support still finds its jar;
* the **directory segment** (``''`` for the default) — the platform's own device directory.

Getting the folds wrong is how two spellings of one login become two files (the panel saves
``zhihu@default_cookies.json``, the crawler reads ``zhihu_cookies.json``) or two cache slots
(a probe pays for a second browser and answers from the slot nobody filled). So the folds live
here, in one place, and ``sessions.cookies`` (the file) and ``sessions.profiles`` (the device)
both ask this module for the NAME instead of re-deriving it.

**Pure by contract**: no filesystem read or write, no clock, no Flask. ``account_order`` and
``next_free_label`` take the facts a caller read off the disk and answer the decision, which is
what lets the rules be tested without a cookie directory.
"""

import os
import re

#: An account label is the ONLY extra segment a cookie filename and a profile directory gain,
#: and it comes from a text box in the panel, so it is held to the same shape as a platform
#: name: it enters a filesystem path. ``@`` separates platform from account and no part may
#: contain it, which is what keeps ``zhihu@work_cookies.json`` unambiguously "zhihu, account
#: work". The empty account is the platform's default login and keeps the pre-multi-account
#: filename byte-for-byte, so an existing single-account user's files never move.
#:
#: The character set is "what a path segment may say and what this tool may fold safely":
#: letters, digits, ``_`` and ``-``. ``.`` and ``..`` are out because they are path parts,
#: ``/`` ``\\`` ``@`` because they are structure, and a space because the panel writes the
#: name into filenames that a shell or a script has to quote afterwards. Uppercase IS
#: accepted at the box, but it is not a distinct account: the key is lowercased here, on a
#: filesystem where ``Work`` and ``work`` are the same file — two spellings of one login is
#: exactly the thing this module refuses to keep.
ACCOUNT_RE = re.compile(r'^[a-z0-9_-]{1,24}$')

#: The platform's own login has a NAME like any other account — ``default`` — because one
#: thing cannot have two rules. It is also the only name spelled two ways: the empty string is
#: its historical spelling (every file, node parameter and workflow written before
#: multi-account support left it blank), so both arrive here and one answer leaves.
DEFAULT_ACCOUNT = 'default'


def account_name(account) -> str:
    """The one spelling of an account label: blank folds to ``default``.

    Returns the *name*, which is what lists, labels and node parameters carry. Path building
    uses :func:`account_segment`, because the default login's file name predates the name.
    """
    text = str(account or '').strip().lower()
    return DEFAULT_ACCOUNT if text == '' else text


def is_default(account) -> bool:
    """Whether *account* names the platform's own login, under either spelling."""
    return account_name(account) == DEFAULT_ACCOUNT


def account_segment(account) -> str:
    """The segment the FILE and the verdict KEY use: ``''`` for the default login.

    ``zhihu_cookies.json`` must stay ``zhihu_cookies.json`` for a user who never named an
    account, and the same is true of every workflow file and run record written before this
    name existed. Public because the preflight cache keys by account too, and a ``default``
    probe that keyed itself apart from a blank one would ask the same question twice.
    """
    return '' if is_default(account) else account_name(account)


def is_account_label(account) -> bool:
    """Whether *account* is a usable label — one rule for every account, the default included.

    ``default`` matches the character rule like any other name, and the empty string is
    accepted because it is that same account's historical spelling, not a second kind of
    account. Folding happens in :func:`account_name`, so no caller tests for ``''``.
    """
    text = str(account or '').strip().lower()
    return text == '' or bool(ACCOUNT_RE.match(text))


def cookie_filename(platform, account='') -> str:
    """``zhihu_cookies.json`` for the default login, ``zhihu@work_cookies.json`` for a named one."""
    segment = account_segment(account)
    stem = f'{platform}@{segment}' if segment else str(platform or '')
    return f'{stem}_cookies.json'


def profile_segment(account) -> str:
    """The validated DIRECTORY segment, or ``''`` for the default (no nesting).

    Raises on a label that is neither blank nor a safe word — the same refusal the cookie file
    makes, so a profile directory can never be walked out of the root.
    """
    account = account_name(account)
    if account == DEFAULT_ACCOUNT:
        return ''
    if not ACCOUNT_RE.match(account):
        raise ValueError(f'Invalid account: {account}')
    return account


def profile_path(root, platform, account='') -> str:
    """``<root>/<platform>`` for the default device, ``<root>/<platform>/<account>`` for a named one."""
    base = str(platform or '').strip()
    part = profile_segment(account)
    return os.path.join(str(root), base, part) if part else os.path.join(str(root), base)


def account_order(accounts, born) -> list:
    """*accounts* in the order they were first created; ties by label.

    ``born`` maps an account to the timestamp its file was created (or ``inf`` when unknown) —
    a caller reads it off the filesystem, so the ORDER is a decision that can be asked without
    one. Creation order, not alphabetical, is what a new node preselects: “节点使用的账号默认
    都是第一个创建的账号”.
    """
    return sorted(accounts, key=lambda account: (born.get(account, float('inf')), account))


def next_free_label(taken) -> str:
    """The label to give a save that was asked to be the default while one already exists.

    “如果有多个留空就需要默认账号后面自动加数字”: the default file is one file, and a second
    unnamed save would otherwise overwrite the first login with no sentence saying so. The
    generated label is ASCII (``default2``, ``default3``…) because it enters a filename — the
    *display* of it is “默认账号2”, which is what the user reads (``account_label_key``).

    A platform with no default login yet answers ``default`` — the name of that slot — so
    every account the panel lists is spelled the same way: a word that fits the rule.
    """
    names = {account_name(name) for name in taken}
    if DEFAULT_ACCOUNT not in names:
        return DEFAULT_ACCOUNT
    step = 2
    while f'default{step}' in names:
        step += 1
    return f'default{step}'
