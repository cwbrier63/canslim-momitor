"""
CANSLIM Monitor - Data Provider Abstraction Layer
==================================================
Provides a unified interface for multiple data sources across three domains:

  Historical  – daily OHLCV bars, moving-average data, intraday volume
  Realtime    – live quotes (polling or streaming)
  Futures     – overnight ES / NQ / YM snapshots

Concrete implementations live in sub-modules (e.g. ``providers.massive``,
``providers.ibkr``) and register themselves via ``ProviderRegistry``.
"""

from canslim_monitor.providers.types import (
    Bar,
    Quote,
    FuturesSnapshot,
    Timeframe,
    ThrottleProfile,
    TierConfig,
    ProviderHealth,
    ProviderType,
    ProviderStatus,
)
from canslim_monitor.providers.base import (
    BaseProvider,
    HistoricalProvider,
    RealtimeProvider,
    FuturesProvider,
)
from canslim_monitor.providers.throttle import RateLimiter
from canslim_monitor.providers.registry import ProviderRegistry
from canslim_monitor.providers.factory import ProviderFactory

# Import concrete providers so they auto-register with the registry
import canslim_monitor.providers.massive  # noqa: F401 — registers MassiveHistoricalProvider
import canslim_monitor.providers.ibkr     # noqa: F401 — registers IBKRRealtimeProvider + IBKRFuturesProvider

__all__ = [
    # Canonical data types
    'Bar',
    'Quote',
    'FuturesSnapshot',
    'Timeframe',
    # Configuration types
    'ThrottleProfile',
    'TierConfig',
    'ProviderHealth',
    'ProviderType',
    'ProviderStatus',
    # Abstract base classes
    'BaseProvider',
    'HistoricalProvider',
    'RealtimeProvider',
    'FuturesProvider',
    # Infrastructure
    'RateLimiter',
    'ProviderRegistry',
    'ProviderFactory',
]
