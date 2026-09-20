"""Event driven backtesting for the ICT models.

Phase 2 covers the Silver Bullet only. The engine, broker, costs and risk
manager are shared, so the remaining models plug into the same machinery in
Phase 3 rather than each growing their own.
"""

from .broker import Broker, Order, Position, Trade
from .costs import CostModel
from .engine import BacktestResult, run
from .report import Metrics, measure, report
from .risk import RiskConfig, RiskManager, position_size
from .walkforward import WalkForward, grid, rank, walk_forward
from .walkforward import report as walk_forward_report
from .models import MODELS, BaseModel, ModelConfig
from .strategy import Context, Setup, Strategy, build_context

__all__ = [
    "BacktestResult",
    "Broker",
    "CostModel",
    "Metrics",
    "Order",
    "Position",
    "RiskConfig",
    "RiskManager",
    "MODELS",
    "BaseModel",
    "Context",
    "ModelConfig",
    "Setup",
    "Strategy",
    "build_context",
    "Trade",
    "measure",
    "WalkForward",
    "grid",
    "position_size",
    "rank",
    "walk_forward",
    "walk_forward_report",
    "report",
    "run",
]
