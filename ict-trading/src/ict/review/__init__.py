"""The AI review layer: the last filter, and the audit that polices it.

The layer may only skip a trade or make it smaller. That is enforced in
:class:`~ict.review.types.Verdict`, not in a prompt, because the input includes
headlines from the internet and a prompt is not a boundary.

Nothing here decides to trade. The strategy decides; this layer gets a veto,
and :func:`~ict.review.audit.audit` decides whether it deserves to keep it.
"""

from .audit import Audit, Decision, Journal, audit
from .reviewers import (
    SYSTEM_PROMPT,
    AlwaysTake,
    ClaudeReviewer,
    Reviewer,
    RuleReviewer,
    parse_verdict,
)
from .types import ACTIONS, ReviewRequest, Verdict

__all__ = [
    "ACTIONS",
    "AlwaysTake",
    "Audit",
    "ClaudeReviewer",
    "Decision",
    "Journal",
    "ReviewRequest",
    "Reviewer",
    "RuleReviewer",
    "SYSTEM_PROMPT",
    "Verdict",
    "audit",
    "parse_verdict",
]
