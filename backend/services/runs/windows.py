"""The time window a workflow's crawl was asked to walk, carried to where a file is named.

A save node receives only a table and cannot see the crawl it sits downstream of, so
「文件名带时间范围」 needs the range to travel through the run. ``note_window`` records it where
the crawl states it; ``window_for_save`` reads it back where the output names its file.
"""

from core.refs import window_tag
from runtime.state import execution_state

from i18n import t


def note_window(wf_idx, start, end) -> None:
    """Remember that a crawl in this workflow was asked to walk a time window.

    Recorded at the crawl, where the window is stated, for the save node downstream,
    which receives only a table and cannot ask. Blank and unparseable pairs are not
    recorded at all: the crawler refuses those itself, and a half-window must not become
    half a filename.

    What is kept is the formatted tag rather than the two strings as typed, because
    「2026-1-1」 and 「2026-01-01」 are the one stretch, and storing the spellings would
    refuse a file there is nothing ambiguous about.
    """
    tag = window_tag(start, end)
    if not tag:
        return
    found = execution_state['_time_windows'].setdefault(wf_idx, [])
    if tag not in found:
        found.append(tag)


def window_for_save(wf_idx) -> tuple:
    """``(tag, refusal)`` — the time window this workflow's file can honestly name.

    One window is the case the user asked for. Zero is a workflow that never asked for a
    range, so 「文件名带时间范围」 has nothing to print; two different ranges is a canvas
    whose single file cannot say which of them it holds. Both answer with the sentence
    rather than a guess, because a filename is a name being chosen — and a saved table
    quietly labelled with the wrong month is worse than one that was not written.
    """
    found = execution_state['_time_windows'].get(wf_idx) or []
    if not found:
        return '', t('export.window_none')
    if len(found) > 1:
        return '', t('export.window_many', n=len(found))
    return found[0], ''
