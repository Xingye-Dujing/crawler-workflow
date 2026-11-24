"""The one rule that spends a user's accounts: may this attempt be replaced by another login?

Rotation is the only place in 继续/采集 where a decision costs something the user cannot get back
— a second login puts that account in front of a site that has just refused it, and the pool's
whole point is that a wall is evidence about ONE pair (login, exit), never about the crawl. So the
rule is a pure function of facts, and every caller hands it the same facts:

* the site must have ATTRIBUTED the refusal to the session (``login_wall``/``risk``) — a timeout,
  a dead ethernet cable or an un-named failure says nothing about the login;
* THIS attempt must have stored nothing — rows already in the store mean the answer was partly
  read, and re-paying for it is the failure the pool was added to *prevent*;
* the node must be in pool mode, the user must not have pressed 停止, and there must be a login
  left to try.

Everything else — how a wall is observed, which candidate is claimed next, which console line
is printed — is I/O and stays with the caller (:mod:`nodes.executors.source`,
:mod:`nodes.executors.comment`).
"""

from dataclasses import dataclass

from services.pool import health

#: Spend the next login on this attempt.
ROTATE = 'rotate'
#: No rotation: settle the attempt as what it is (a partial table, a failed node, a 风控 back-off).
SETTLE = 'settle'


@dataclass(frozen=True)
class Attempt:
    """What one browser attempt proved, as far as the rotation rule is concerned."""

    #: The pool's own word for what happened (``login_wall``/``risk``/``network``/``''``).
    reason: str = ''
    #: Rows THIS attempt stored. Negative is read as zero: a re-linked node's count can only be
    #: reconciled against its own baseline, never used as evidence of fresh work.
    stored_rows: int = 0
    #: Whether the node is rotating at all (``@pool`` account, pool mode on).
    pooled: bool = True
    #: The user pressed 停止: a stop is an instruction, not a measurement about the session.
    stopped: bool = False
    #: Logins this node may still spend. ``None`` means the caller is not the budget holder and
    #: is asking only "does this outcome justify another login?".
    attempts_left: int | None = None


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str

    def rotates(self) -> bool:
        return self.action == ROTATE


def decide(attempt: Attempt) -> Decision:
    """The rule, in one place, with no I/O and no clock."""
    reason = str(attempt.reason or '')
    settle = Decision(SETTLE, reason)
    if attempt.stopped:
        return settle
    if not attempt.pooled:
        return settle
    if not health.is_rotatable(reason):
        # An un-attributed failure (or a network fault) is not evidence against the login.
        return settle
    if int(attempt.stored_rows or 0) > 0:
        # Part of this attempt's answer was already read and stored; rotating drops it.
        return settle
    if attempt.attempts_left is not None and int(attempt.attempts_left) <= 0:
        return settle
    return Decision(ROTATE, reason)
