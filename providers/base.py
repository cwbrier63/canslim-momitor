"""
CANSLIM Monitor - Provider Abstract Base Classes
=================================================
Three domain-specific ABCs that every provider must implement:

  HistoricalProvider  – daily bars, moving-average data, intraday volume
  RealtimeProvider    – live quotes (polling or streaming)
  FuturesProvider     – overnight ES / NQ / YM snapshots

Each ABC inherits ``BaseProvider`` which wires up:
  - ThrottleProfile-driven rate limiting (token bucket + 429 back-off)
  - ProviderHealth bookkeeping (success / failure / latency tracking)
  - Optional OAuth refresh hook (``refresh_auth()``)

Concrete providers (Massive, IBKR, Schwab, …) subclass one or more of
these ABCs and are registered via ``ProviderRegistry``.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Dict, Optional, Callable
import logging
import time

from canslim_monitor.providers.types import (
    Bar, Quote, FuturesSnapshot, Timeframe,
    ThrottleProfile, ProviderHealth, ProviderStatus,
)
from canslim_monitor.providers.throttle import RateLimiter


class BaseProvider(ABC):
    """Shared foundation for every data provider."""

    def __init__(
        self,
        name: str,
        throttle_profile: Optional[ThrottleProfile] = None,
        logger: logging.Logger = None,
    ):
        self._name = name
        self._logger = logger or logging.getLogger(f"provider.{name}")
        self._limiter = (
            RateLimiter(throttle_profile, self._logger)
            if throttle_profile
            else None
        )
        self._health = ProviderHealth(
            provider_name=name, status=ProviderStatus.ACTIVE
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def health(self) -> ProviderHealth:
        return self._health

    # ------------------------------------------------------------------
    # Lifecycle (override in subclasses)
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the provider.  Returns True on success."""
        ...

    @abstractmethod
    def disconnect(self):
        """Release connection resources."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the provider is currently usable."""
        ...

    def refresh_auth(self) -> bool:
        """Refresh an OAuth / API token.

        Override for providers whose tokens expire (e.g. Schwab 30-min
        access tokens).  The default implementation is a no-op that
        returns True.
        """
        return True

    # ------------------------------------------------------------------
    # Rate-limiting helpers (call from subclass data methods)
    # ------------------------------------------------------------------

    def _throttle(self):
        """Block until the rate limiter allows a call."""
        if self._limiter:
            self._limiter.acquire()

    def _record_success(self, latency_ms: Optional[float] = None):
        """Update health after a successful API call."""
        self._health.status = ProviderStatus.ACTIVE
        self._health.last_success = datetime.now()
        self._health.consecutive_failures = 0
        self._health.error_message = None
        if latency_ms is not None:
            self._health.latency_ms = latency_ms
        if self._limiter:
            self._limiter.report_success()

    def _record_failure(self, error: str, is_rate_limit: bool = False):
        """Update health after a failed API call."""
        self._health.consecutive_failures += 1
        self._health.last_failure = datetime.now()
        self._health.error_message = error
        if is_rate_limit:
            self._health.status = ProviderStatus.RATE_LIMITED
            if self._limiter:
                self._limiter.report_429()
        elif self._health.consecutive_failures >= 3:
            self._health.status = ProviderStatus.DOWN
        else:
            self._health.status = ProviderStatus.DEGRADED

    def _timed_call(self, fn, *args, **kwargs):
        """Execute *fn* with throttle + latency tracking.

        Returns the result of *fn*.  On HTTP-429 the failure is recorded
        automatically and the call is **not** retried (the caller can
        decide to retry).
        """
        self._throttle()
        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            latency = (time.perf_counter() - t0) * 1000
            self._record_success(latency_ms=latency)
            return result
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            is_429 = "429" in str(exc) or "rate limit" in str(exc).lower()
            self._record_failure(str(exc), is_rate_limit=is_429)
            raise


# ======================================================================
# Domain ABCs
# ======================================================================

class HistoricalProvider(BaseProvider):
    """Provider for historical daily bar data and intraday volume."""

    @abstractmethod
    def get_daily_bars(
        self,
        symbol: str,
        days: int = 50,
        end_date: Optional[date] = None,
    ) -> List[Bar]:
        """Return *days* daily OHLCV bars for *symbol*, ending at *end_date*
        (defaults to today / most recent trading day).
        """
        ...

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAY,
        count: int = 252,
        end_date: Optional[date] = None,
    ) -> List[Bar]:
        """Return OHLCV bars at the given *timeframe* resolution.

        Subclasses that support multi-timeframe data should override this.
        The default implementation delegates to ``get_daily_bars()`` for
        DAY and WEEK timeframes (WEEK via downsampling) and returns an
        empty list for intraday timeframes.
        """
        if timeframe == Timeframe.DAY:
            return self.get_daily_bars(symbol, days=count, end_date=end_date)
        if timeframe == Timeframe.WEEK:
            # Fetch enough daily bars, then downsample
            daily = self.get_daily_bars(symbol, days=count * 5, end_date=end_date)
            return self._downsample_to_weekly(daily)
        return []

    @staticmethod
    def _downsample_to_weekly(daily_bars: List[Bar]) -> List[Bar]:
        """Aggregate daily bars into weekly bars (Mon-Fri)."""
        if not daily_bars:
            return []
        weeks: Dict[str, list] = {}
        for bar in daily_bars:
            # ISO week key: year-week
            iso = bar.bar_date.isocalendar()
            key = f"{iso[0]}-{iso[1]:02d}"
            weeks.setdefault(key, []).append(bar)
        result = []
        for bars in weeks.values():
            result.append(Bar(
                symbol=bars[0].symbol,
                bar_date=bars[-1].bar_date,   # use Friday (last day of week)
                open=bars[0].open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
                volume=sum(b.volume for b in bars),
            ))
        result.sort(key=lambda b: b.bar_date)
        return result

    @abstractmethod
    def get_intraday_volume(self, symbol: str) -> Optional[Dict]:
        """Return current-day cumulative volume data.

        Expected dict keys (matching existing PolygonClient return):
        ``cumulative_volume``, ``last_price``, ``bars_count``, ``high``, ``low``.
        Returns None if unavailable.
        """
        ...


class RealtimeProvider(BaseProvider):
    """Provider for live quote data (polling or streaming)."""

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch a live quote for a single symbol."""
        ...

    @abstractmethod
    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch live quotes for multiple symbols.

        Returns a dict keyed by symbol.  Missing symbols are omitted.
        """
        ...

    # ------------------------------------------------------------------
    # Streaming hooks (override for WebSocket / SSE providers)
    # ------------------------------------------------------------------

    def supports_streaming(self) -> bool:
        """Return True if this provider supports push-based quotes."""
        return False

    def subscribe(self, symbols: List[str], callback: Callable[[Quote], None]) -> bool:
        """Subscribe to streaming quotes for *symbols*.

        *callback* is invoked on each incoming quote.  Override only if
        ``supports_streaming()`` returns True.
        """
        raise NotImplementedError(f"{self.name} does not support streaming")

    def unsubscribe(self, symbols: List[str]):
        """Unsubscribe from streaming quotes."""
        raise NotImplementedError(f"{self.name} does not support streaming")


class FuturesProvider(BaseProvider):
    """Provider for overnight / pre-market futures snapshots."""

    @abstractmethod
    def get_futures_snapshot(self) -> FuturesSnapshot:
        """Return current ES / NQ / YM change percentages."""
        ...
