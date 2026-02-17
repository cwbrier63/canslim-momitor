"""
CANSLIM Monitor - Massive (Polygon) Providers
==============================================
Historical + Realtime (delayed) providers backed by the Polygon REST API.

Historical provider:
  - Wraps ``PolygonClient.get_daily_bars()`` behind the ``HistoricalProvider`` ABC
  - Canonical ``Bar`` return type, ThrottleProfile, ProviderHealth bookkeeping

Realtime provider (Phase 7):
  - Wraps ``PolygonClient.get_snapshot()`` behind the ``RealtimeProvider`` ABC
  - Returns 15-minute-delayed quotes on the Stocks Starter tier
  - Serves as a fallback when IBKR is unavailable (e.g. GUI without IB Gateway)
  - 60-second response cache to respect the 5 calls/min rate limit

Usage (via factory):
    factory = ProviderFactory(db_session_factory)
    historical = factory.get_historical()        # -> MassiveHistoricalProvider
    realtime   = factory.get_realtime()          # -> MassiveRealtimeProvider (if IBKR down)
"""

import logging
import time
import threading
from datetime import date, datetime
from typing import List, Dict, Optional

from canslim_monitor.providers.base import HistoricalProvider, RealtimeProvider
from canslim_monitor.providers.types import Bar, Quote, Timeframe, ThrottleProfile
from canslim_monitor.providers.registry import ProviderRegistry
from canslim_monitor.integrations.polygon_client import (
    PolygonClient,
    Bar as PolygonBar,
)


class MassiveHistoricalProvider(HistoricalProvider):
    """Historical data provider backed by Massive.com / Polygon.io REST API.

    Wraps ``PolygonClient`` and converts its return types into canonical
    ``providers.Bar`` objects.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = None,
        timeout: int = 30,
        rate_limit_delay: float = 0.5,
        throttle_profile: ThrottleProfile = None,
        logger: logging.Logger = None,
    ):
        super().__init__(
            name="massive_historical",
            throttle_profile=throttle_profile,
            logger=logger,
        )
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._rate_limit_delay = rate_limit_delay

        # Lazy-init the underlying client
        self._client: Optional[PolygonClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        try:
            self._client = PolygonClient(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                rate_limit_delay=self._rate_limit_delay,
                logger=self._logger,
            )
            connected = self._client.test_connection()
            if connected:
                self._record_success()
            else:
                self._record_failure("test_connection returned False")
            return connected
        except Exception as exc:
            self._record_failure(str(exc))
            return False

    def disconnect(self):
        self._client = None

    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Optional[PolygonClient]:
        """Expose underlying PolygonClient for legacy callers that need it."""
        return self._client

    # ------------------------------------------------------------------
    # HistoricalProvider interface
    # ------------------------------------------------------------------

    def get_daily_bars(
        self,
        symbol: str,
        days: int = 50,
        end_date: Optional[date] = None,
    ) -> List[Bar]:
        if not self._client:
            self._logger.warning("get_daily_bars called before connect()")
            return []

        try:
            polygon_bars: List[PolygonBar] = self._timed_call(
                self._client.get_daily_bars, symbol, days, end_date
            )
            return [self._convert_bar(b) for b in polygon_bars]
        except Exception as exc:
            self._logger.error("get_daily_bars(%s) failed: %s", symbol, exc)
            return []

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAY,
        count: int = 252,
        end_date: Optional[date] = None,
    ) -> List[Bar]:
        if not self._client:
            self._logger.warning("get_bars called before connect()")
            return []

        try:
            polygon_bars = self._timed_call(
                self._client.get_bars,
                symbol,
                timeframe.value,
                count,
                end_date,
            )
            return [self._convert_bar(b) for b in polygon_bars]
        except Exception as exc:
            self._logger.error("get_bars(%s, %s) failed: %s", symbol, timeframe.value, exc)
            return []

    def get_intraday_volume(self, symbol: str) -> Optional[Dict]:
        if not self._client:
            self._logger.warning("get_intraday_volume called before connect()")
            return None

        try:
            return self._timed_call(self._client.get_intraday_volume, symbol)
        except Exception as exc:
            self._logger.error("get_intraday_volume(%s) failed: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Pass-through helpers for callers that need polygon-specific methods
    # ------------------------------------------------------------------

    def get_next_earnings_date(self, symbol: str) -> Optional[date]:
        """Convenience pass-through to PolygonClient.get_next_earnings_date."""
        if not self._client:
            return None
        try:
            return self._timed_call(self._client.get_next_earnings_date, symbol)
        except Exception:
            return None

    def get_ticker_details(self, symbol: str) -> Optional[Dict]:
        """Convenience pass-through to PolygonClient.get_ticker_details."""
        if not self._client:
            return None
        try:
            return self._timed_call(self._client.get_ticker_details, symbol)
        except Exception:
            return None

    def calculate_average_volume(self, bars: List[Bar], days: int = 50) -> int:
        """Calculate average volume from canonical Bar list."""
        if not bars:
            return 0
        recent = bars[-days:] if len(bars) > days else bars
        total = sum(b.volume for b in recent)
        return int(total / len(recent)) if recent else 0

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_bar(pb: PolygonBar) -> Bar:
        """Convert polygon_client.Bar -> canonical providers.Bar."""
        bar = Bar(
            symbol=pb.symbol,
            bar_date=pb.bar_date,
            open=pb.open,
            high=pb.high,
            low=pb.low,
            close=pb.close,
            volume=pb.volume,
            vwap=pb.vwap,
            transactions=pb.transactions,
        )
        # Preserve intraday timestamp if set by PolygonClient.get_bars()
        if hasattr(pb, '_timestamp_ms'):
            bar._timestamp_ms = pb._timestamp_ms
        return bar


class MassiveRealtimeProvider(RealtimeProvider):
    """Delayed-quote provider backed by Polygon's snapshot endpoint.

    On the Stocks Starter tier, quotes are **15-minute delayed**.  This
    provider is intended as a fallback when IBKR is not connected — useful
    for the GUI kanban board, CLI tools, and testing.

    Rate-limit friendly:
    - Caches each symbol's snapshot for ``cache_seconds`` (default 60s).
    - Batch ``get_quotes()`` calls ``get_snapshot()`` once per symbol.
    - Stays well within the 5 calls/min Starter-tier budget.
    """

    DEFAULT_CACHE_SECONDS = 60

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = None,
        timeout: int = 30,
        rate_limit_delay: float = 0.5,
        cache_seconds: int = None,
        throttle_profile: ThrottleProfile = None,
        logger: logging.Logger = None,
    ):
        super().__init__(
            name="massive_realtime",
            throttle_profile=throttle_profile,
            logger=logger,
        )
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._rate_limit_delay = rate_limit_delay
        self._cache_seconds = cache_seconds if cache_seconds is not None else self.DEFAULT_CACHE_SECONDS

        self._client: Optional[PolygonClient] = None

        # Thread-safe cache: {symbol: (Quote, timestamp)}
        self._cache: Dict[str, tuple] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        try:
            self._client = PolygonClient(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                rate_limit_delay=self._rate_limit_delay,
                logger=self._logger,
            )
            connected = self._client.test_connection()
            if connected:
                self._record_success()
            else:
                self._record_failure("test_connection returned False")
            return connected
        except Exception as exc:
            self._record_failure(str(exc))
            return False

    def disconnect(self):
        self._client = None
        with self._cache_lock:
            self._cache.clear()

    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Optional[PolygonClient]:
        """Expose underlying PolygonClient (shares with historical if needed)."""
        return self._client

    # ------------------------------------------------------------------
    # RealtimeProvider interface
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Return a delayed snapshot quote, served from cache if fresh."""
        if not self._client:
            return None

        # Check cache
        cached = self._get_cached(symbol)
        if cached is not None:
            return cached

        try:
            snap = self._timed_call(self._client.get_snapshot, symbol)
            if not snap or snap.get('last', 0) <= 0:
                return None

            quote = Quote(
                symbol=snap['symbol'],
                last=snap['last'],
                open=snap.get('open'),
                high=snap.get('high'),
                low=snap.get('low'),
                volume=int(snap.get('volume', 0)) or None,
                avg_volume=int(snap.get('avg_volume', 0)) or None,
                close=snap.get('prev_close'),
                timestamp=datetime.fromtimestamp(snap['timestamp'] / 1000)
                    if snap.get('timestamp') else None,
            )
            self._put_cached(symbol, quote)
            return quote
        except Exception as exc:
            self._logger.debug("get_quote(%s) failed: %s", symbol, exc)
            return None

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch delayed quotes for multiple symbols (one API call each)."""
        results: Dict[str, Quote] = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q is not None:
                results[sym] = q
        return results

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cached(self, symbol: str) -> Optional[Quote]:
        with self._cache_lock:
            entry = self._cache.get(symbol.upper())
            if entry:
                quote, ts = entry
                if time.time() - ts < self._cache_seconds:
                    return quote
        return None

    def _put_cached(self, symbol: str, quote: Quote):
        with self._cache_lock:
            self._cache[symbol.upper()] = (quote, time.time())


# ---------------------------------------------------------------------------
# Auto-register with the provider registry at import time
# ---------------------------------------------------------------------------
ProviderRegistry.register_historical("massive", MassiveHistoricalProvider)
ProviderRegistry.register_realtime("massive", MassiveRealtimeProvider)
