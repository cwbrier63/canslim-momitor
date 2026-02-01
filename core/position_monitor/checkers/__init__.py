"""
Position Monitor Checkers Package

Individual alert checkers for position monitoring.
"""

from .base_checker import BaseChecker, PositionContext
from .stop_checker import StopChecker
from .profit_checker import ProfitChecker
from .pyramid_checker import PyramidChecker
from .ma_checker import MAChecker
from .health_checker import HealthChecker
from .reentry_checker import ReentryChecker
from .watchlist_alt_entry_checker import WatchlistAltEntryChecker

__all__ = [
    'BaseChecker',
    'PositionContext',
    'StopChecker',
    'ProfitChecker',
    'PyramidChecker',
    'MAChecker',
    'HealthChecker',
    'ReentryChecker',
    'WatchlistAltEntryChecker',
]

# Default checker instances
DEFAULT_CHECKERS = [
    StopChecker,
    ProfitChecker,
    PyramidChecker,
    MAChecker,
    HealthChecker,
    ReentryChecker,
    WatchlistAltEntryChecker,
]
