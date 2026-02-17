"""
CANSLIM Monitor - Provider Canonical Types
==========================================
Defines the shared data types used across all provider implementations.
These types decouple consumers from provider-specific formats.

Reconciliation:
- Bar: unifies polygon_client.Bar (symbol+bar_date) and historical_data.DailyBar (date only)
- Quote: unifies IBKR get_quote() dict format
- FuturesSnapshot: unifies ibkr_futures (es, nq, ym) tuple
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict
from enum import Enum


class Timeframe(Enum):
    """Chart resolution / bar timeframe."""
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"
    MINUTE_30 = "30min"

    @property
    def display_label(self) -> str:
        return {"week": "W", "day": "D", "hour": "1H", "30min": "30m"}[self.value]

    @property
    def is_intraday(self) -> bool:
        return self in (Timeframe.HOUR, Timeframe.MINUTE_30)


class ProviderType(Enum):
    """Domain a provider serves."""
    HISTORICAL = "historical"
    REALTIME = "realtime"
    FUTURES = "futures"


class ProviderStatus(Enum):
    """Current health state of a provider."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    DOWN = "down"
    RATE_LIMITED = "rate_limited"


# ---------------------------------------------------------------------------
# Canonical market-data types
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """Canonical daily OHLCV bar.

    Field names follow the existing polygon_client.Bar convention so that
    the Massive provider wrapper is a thin pass-through.  Consumers that
    previously used historical_data.DailyBar should map ``date`` -> ``bar_date``
    and supply the ``symbol`` field.
    """
    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    transactions: Optional[int] = None

    def to_dict(self) -> Dict:
        """Legacy-compatible dict (matches DailyBar.to_dict keys)."""
        return {
            'date': self.bar_date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }


@dataclass
class Quote:
    """Canonical live quote.

    Field names follow the existing IBKR get_quote() dict so that the
    IBKR realtime provider wrapper is a thin pass-through.
    """
    symbol: str
    last: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    avg_volume: Optional[int] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    close: Optional[float] = None
    timestamp: Optional[datetime] = None
    volume_available: bool = True

    def to_dict(self) -> Dict:
        """Legacy-compatible dict (matches IBKR get_quote() return)."""
        return {
            'symbol': self.symbol,
            'last': self.last,
            'bid': self.bid,
            'ask': self.ask,
            'volume': self.volume,
            'avg_volume': self.avg_volume,
            'high': self.high,
            'low': self.low,
            'open': self.open,
            'close': self.close,
            'volume_available': self.volume_available,
        }


@dataclass
class FuturesSnapshot:
    """Canonical futures snapshot.

    Matches the existing ibkr_futures.get_futures_snapshot() return of
    (es_change_pct, nq_change_pct, ym_change_pct).
    """
    es_change_pct: float = 0.0
    nq_change_pct: float = 0.0
    ym_change_pct: float = 0.0
    timestamp: Optional[datetime] = None

    def to_tuple(self) -> tuple:
        """Legacy-compatible (es, nq, ym) tuple."""
        return (self.es_change_pct, self.nq_change_pct, self.ym_change_pct)


# ---------------------------------------------------------------------------
# Provider configuration types
# ---------------------------------------------------------------------------

@dataclass
class ThrottleProfile:
    """Rate-limiting configuration for a provider tier.

    ``calls_per_minute`` drives the sustained token-bucket refill rate.
    ``burst_size`` allows short spikes above the sustained rate.
    ``min_delay_seconds`` enforces a hard floor between consecutive calls.
    ``backoff_factor`` / ``max_backoff_seconds`` control exponential back-off
    after a 429 (rate-limit) response.
    """
    calls_per_minute: int
    burst_size: int = 0
    min_delay_seconds: float = 0.0
    backoff_factor: float = 2.0
    max_backoff_seconds: float = 60.0


@dataclass
class TierConfig:
    """Provider subscription tier and its capabilities."""
    tier_name: str
    throttle: ThrottleProfile
    features: Dict = field(default_factory=dict)


@dataclass
class ProviderHealth:
    """Runtime health snapshot for a provider instance."""
    provider_name: str
    status: ProviderStatus = ProviderStatus.ACTIVE
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None
