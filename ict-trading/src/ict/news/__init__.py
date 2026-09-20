"""The news module: calendar, the entry gate, and the two playbooks.

The gate is a risk check that code enforces and nothing overrides. The
playbooks are a separate strategy from the ICT models, tested on their own
record, and they are deliberately absent from
:data:`~ict.backtest.models.MODELS` so they can never drift into an ICT
ranking.
"""

from .calendar import (
    DEFAULT_BLACKOUT_MINUTES,
    Event,
    events,
    read_calendar,
    scaled_surprise,
)
from .gate import Blackout, NewsGate, gated_minutes
from .playbooks import (
    PLAYBOOKS,
    DirectionalPlaybook,
    NewsConfig,
    NewsCostModel,
    SpikeCorrectionPlaybook,
)

__all__ = [
    "Blackout",
    "DEFAULT_BLACKOUT_MINUTES",
    "DirectionalPlaybook",
    "Event",
    "NewsConfig",
    "NewsCostModel",
    "NewsGate",
    "PLAYBOOKS",
    "SpikeCorrectionPlaybook",
    "events",
    "gated_minutes",
    "read_calendar",
    "scaled_surprise",
]
