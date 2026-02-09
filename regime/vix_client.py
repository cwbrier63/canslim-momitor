"""
CANSLIM Monitor - CBOE VIX Client
===================================
Fetches CBOE Volatility Index (VIX) data for market sentiment display.

Uses IBKR Index contract when available, falls back to Yahoo Finance.
Yahoo Finance also provides historical data for seeding.
"""

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Optional, List, Tuple

import requests

logger = logging.getLogger('canslim.regime')

YAHOO_VIX_URL = 'https://query2.finance.yahoo.com/v8/finance/chart/%5EVIX'

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


@dataclass
class VixData:
    """VIX data point."""
    close: float              # Current VIX level
    previous_close: float     # Previous day's close
    timestamp: datetime       # When fetched


def classify_vix(level: float) -> str:
    """Classify VIX level into human-readable category (IBD/MarketSurge-aligned thresholds)."""
    if level >= 45:
        return "Extreme Fear"
    elif level >= 30:
        return "Very High"
    elif level >= 25:
        return "High"
    elif level >= 20:
        return "Elevated"
    elif level >= 15:
        return "Normal"
    elif level >= 12:
        return "Low Volatility"
    else:
        return "Extreme Complacency"


def get_vix_emoji(level: float) -> str:
    """Get emoji for VIX level."""
    if level >= 45:
        return '\U0001f631'   # face screaming in fear - Extreme Fear
    elif level >= 30:
        return '\U0001f628'   # fearful face - Very High
    elif level >= 25:
        return '\U0001f6a8'   # rotating light - High
    elif level >= 20:
        return '\U0001f7e1'   # yellow circle - Elevated
    elif level >= 15:
        return '\U0001f7e2'   # green circle - Normal
    elif level >= 12:
        return '\U0001f60e'   # sunglasses face - Low Volatility
    else:
        return '\U0001f4a4'   # zzz - Extreme Complacency


class VixClient:
    """
    Client for fetching VIX data.

    Tries IBKR Index contract first, falls back to Yahoo Finance.
    Results are cached in-memory for the configured duration.
    """

    def __init__(self, ibkr_client=None, cache_minutes: int = 30):
        self._ibkr_client = ibkr_client
        self._cache_minutes = cache_minutes
        self._cached: Optional[VixData] = None
        self._cache_time: Optional[datetime] = None
        self._timeout = 10

    @classmethod
    def from_config(cls, config: dict, ibkr_client=None) -> 'VixClient':
        """Create client from application config."""
        vix_config = config.get('market_regime', {}).get('vix', {})
        cache_minutes = vix_config.get('cache_minutes', 30)
        return cls(ibkr_client=ibkr_client, cache_minutes=cache_minutes)

    def fetch_current(self) -> Optional[VixData]:
        """
        Fetch current VIX level.

        Tries IBKR first, falls back to Yahoo Finance.
        Returns cached data if within cache window.
        Returns None on any failure (non-critical data source).
        """
        # Check cache
        if self._cached and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_minutes * 60:
                logger.debug(f"Using cached VIX data (age: {elapsed:.0f}s)")
                return self._cached

        # Try IBKR first
        data = self._fetch_from_ibkr()

        # Fall back to Yahoo Finance
        if not data:
            data = self._fetch_from_yahoo()

        if data:
            self._cached = data
            self._cache_time = datetime.now()
            logger.info(f"VIX: {data.close:.2f} (prev: {data.previous_close:.2f})")

        return data

    def fetch_historical(self, days: int = 365) -> List[Tuple[date, float]]:
        """
        Fetch historical daily VIX close data from Yahoo Finance.

        Returns list of (date, close) tuples, oldest first.
        """
        try:
            end_ts = int(datetime.now().timestamp())
            start_ts = int((datetime.now() - timedelta(days=days)).timestamp())

            params = {
                'interval': '1d',
                'period1': start_ts,
                'period2': end_ts,
            }

            # Retry with backoff for rate limiting (429)
            data = None
            for attempt in range(3):
                headers = {'User-Agent': random.choice(USER_AGENTS)}
                resp = requests.get(YAHOO_VIX_URL, params=params, headers=headers, timeout=self._timeout)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 5
                    logger.debug(f"Yahoo Finance rate limited, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break

            if data is None:
                logger.warning("Yahoo Finance rate limit persisted after retries")
                return []

            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            closes = result['indicators']['quote'][0]['close']

            points = []
            for ts, close in zip(timestamps, closes):
                if close is not None:
                    dt = datetime.fromtimestamp(ts).date()
                    points.append((dt, round(float(close), 2)))

            # Sort oldest first
            points.sort(key=lambda p: p[0])
            logger.info(f"Fetched {len(points)} historical VIX data points")
            return points

        except Exception as e:
            logger.warning(f"Failed to fetch VIX history: {e}")
            return []

    def _fetch_from_ibkr(self) -> Optional[VixData]:
        """Get VIX from IBKR using Index contract."""
        if not self._ibkr_client:
            return None

        if not self._ibkr_client.is_connected():
            return None

        try:
            quote = self._ibkr_client.get_quote('VIX')
            if quote:
                last = quote.get('last') or quote.get('close')
                prev = quote.get('close') or quote.get('prev_close')
                if last and last > 0:
                    return VixData(
                        close=float(last),
                        previous_close=float(prev) if prev and prev > 0 else 0.0,
                        timestamp=datetime.now(),
                    )
        except Exception as e:
            logger.debug(f"IBKR VIX fetch failed: {e}")

        return None

    def _fetch_from_yahoo(self) -> Optional[VixData]:
        """Get VIX from Yahoo Finance with retry for rate limiting."""
        for attempt in range(3):
            try:
                params = {'interval': '1d', 'range': '2d'}
                headers = {'User-Agent': random.choice(USER_AGENTS)}

                resp = requests.get(YAHOO_VIX_URL, params=params, headers=headers, timeout=self._timeout)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 3
                    logger.debug(f"Yahoo Finance VIX rate limited, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()

                result = data['chart']['result'][0]
                meta = result['meta']
                price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('chartPreviousClose') or meta.get('previousClose', 0)

                if price and price > 0:
                    return VixData(
                        close=float(price),
                        previous_close=float(prev_close) if prev_close else 0.0,
                        timestamp=datetime.now(),
                    )

            except Exception as e:
                logger.debug(f"Yahoo Finance VIX fetch failed: {e}")

        return None
