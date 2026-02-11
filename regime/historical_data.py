"""
Historical Data Client for Distribution Day Calculation
========================================================

Fetches daily OHLCV data from Massive.com (Polygon.io) API.
Now supports both ETFs (SPY, QQQ) and actual indices (SPX, COMP).

Index Symbols for Polygon/Massive:
- S&P 500:          I:SPX
- Nasdaq Composite: I:COMP (or I:IXIC)
- Nasdaq 100:       I:NDX
- Dow Jones:        I:DJI

Note: Index data doesn't include volume, so we use corresponding
ETF volume (SPY for SPX, QQQ for COMP) for distribution day calculation.

Requirements:
    pip install polygon-api-client

API Key:
    Set POLYGON_API_KEY or MASSIVE_API_KEY environment variable.
"""

import os
import time
import logging
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DailyBar:
    """Single daily OHLCV bar."""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    def to_dict(self) -> Dict:
        return {
            'date': self.date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


# Symbol mapping: what we want -> what Polygon uses
INDEX_SYMBOLS = {
    # Actual indices (no volume)
    'SPX': 'I:SPX',      # S&P 500 Index
    'COMP': 'I:COMP',    # Nasdaq Composite
    'IXIC': 'I:COMP',    # Nasdaq Composite (alternate name)
    'NDX': 'I:NDX',      # Nasdaq 100
    'DJI': 'I:DJI',      # Dow Jones Industrial
    'INDU': 'I:DJI',     # Dow Jones (alternate name)
    
    # ETFs (have volume)
    'SPY': 'SPY',
    'QQQ': 'QQQ',
    'DIA': 'DIA',
}

# For volume data, map indices to their corresponding ETFs
INDEX_TO_ETF_VOLUME = {
    'I:SPX': 'SPY',
    'I:COMP': 'QQQ',
    'I:NDX': 'QQQ',
    'I:DJI': 'DIA',
    'SPX': 'SPY',
    'COMP': 'QQQ',
    'NDX': 'QQQ',
    'DJI': 'DIA',
}


class MassiveHistoricalClient:
    """
    Client for fetching daily OHLCV data from Massive.com (Polygon.io).
    
    Supports both ETFs and actual market indices.
    For indices, volume is fetched from corresponding ETF.
    
    Usage:
        client = MassiveHistoricalClient()
        
        # Fetch actual S&P 500 index with SPY volume
        bars = client.get_daily_bars('SPX', lookback_days=35)
        
        # Or use ETF directly
        bars = client.get_daily_bars('SPY', lookback_days=35)
    """
    
    REQUEST_DELAY_SECONDS = 0.25  # Paid tier (increase for free tier)
    
    def __init__(self, api_key: str = None, request_delay: float = None):
        """
        Initialize client.
        
        Args:
            api_key: Massive.com/Polygon API key. 
                     Falls back to MASSIVE_API_KEY or POLYGON_API_KEY env var.
            request_delay: Override default rate limit delay.
        """
        self.api_key = (
            api_key or 
            os.environ.get('MASSIVE_API_KEY') or 
            os.environ.get('POLYGON_API_KEY')
        )
        if not self.api_key:
            raise ValueError(
                "No Polygon/Massive.com API key provided. "
                "Set MASSIVE_API_KEY or POLYGON_API_KEY environment variable."
            )
        
        self.request_delay = request_delay if request_delay is not None else self.REQUEST_DELAY_SECONDS
        self.client = None
        self._last_request_time = 0
    
    @classmethod
    def from_config(cls, config: dict) -> 'MassiveHistoricalClient':
        """Create client from config dictionary."""
        # Try multiple config paths
        api_key = (
            config.get('market_data', {}).get('api_key') or
            config.get('massive', {}).get('api_key') or
            config.get('polygon', {}).get('api_key') or
            os.environ.get('MASSIVE_API_KEY') or
            os.environ.get('POLYGON_API_KEY')
        )
        request_delay = (
            config.get('market_data', {}).get('request_delay') or
            config.get('massive', {}).get('request_delay') or
            config.get('polygon', {}).get('request_delay')
        )
        
        return cls(api_key=api_key, request_delay=request_delay)
    
    def connect(self) -> bool:
        """Initialize the Polygon REST client."""
        try:
            from polygon import RESTClient
            self.client = RESTClient(api_key=self.api_key)
            logger.info("Connected to Massive.com (Polygon) API")
            return True
        except ImportError:
            raise ImportError(
                "polygon-api-client not installed. Run: pip install polygon-api-client"
            )
        except Exception as e:
            logger.error(f"Failed to connect to Massive.com: {e}")
            raise
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        if self.request_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            sleep_time = self.request_delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    def _get_polygon_symbol(self, symbol: str) -> str:
        """Convert symbol to Polygon format."""
        return INDEX_SYMBOLS.get(symbol.upper(), symbol.upper())
    
    def _needs_volume_from_etf(self, symbol: str) -> Optional[str]:
        """Check if symbol needs volume from an ETF."""
        polygon_symbol = self._get_polygon_symbol(symbol)
        return INDEX_TO_ETF_VOLUME.get(polygon_symbol) or INDEX_TO_ETF_VOLUME.get(symbol.upper())
    
    def get_daily_bars(
        self,
        symbol: str,
        lookback_days: int = 35,
        end_date: date = None
    ) -> List[DailyBar]:
        """
        Fetch daily OHLCV bars for a symbol.
        
        For indices (SPX, COMP, etc.), price data comes from the index
        and volume comes from the corresponding ETF.
        
        Args:
            symbol: Ticker symbol (e.g., 'SPX', 'COMP', 'SPY', 'QQQ')
            lookback_days: Number of calendar days to fetch (default 35)
            end_date: End date for data (default: today)
        
        Returns:
            List of DailyBar objects, sorted oldest to newest
        """
        if not self.client:
            self.connect()
        
        polygon_symbol = self._get_polygon_symbol(symbol)
        etf_for_volume = self._needs_volume_from_etf(symbol)
        
        # Fetch price data
        price_bars = self._fetch_bars(polygon_symbol, lookback_days, end_date)
        
        # If this is an index, we need to get volume from ETF
        if etf_for_volume and etf_for_volume != symbol.upper():
            logger.info(f"Fetching volume data from {etf_for_volume} for {symbol}")
            volume_bars = self._fetch_bars(etf_for_volume, lookback_days, end_date)
            
            # Create volume lookup by date
            volume_by_date = {bar.date: bar.volume for bar in volume_bars}
            
            # Merge volume into price bars
            merged_bars = []
            for bar in price_bars:
                volume = volume_by_date.get(bar.date, 0)
                merged_bars.append(DailyBar(
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=volume
                ))
            return merged_bars
        
        return price_bars
    
    def _fetch_bars(
        self,
        polygon_symbol: str,
        lookback_days: int,
        end_date: date = None
    ) -> List[DailyBar]:
        """Fetch bars from Polygon API."""
        self._rate_limit()
        
        end_dt = end_date or date.today()
        start_dt = end_dt - timedelta(days=lookback_days)
        
        try:
            aggs = self.client.get_aggs(
                ticker=polygon_symbol,
                multiplier=1,
                timespan="day",
                from_=start_dt.strftime('%Y-%m-%d'),
                to=end_dt.strftime('%Y-%m-%d'),
                limit=50000
            )
            
            bars = []
            for agg in aggs:
                # Use UTC to avoid timezone shift issues
                # Polygon timestamps are in UTC milliseconds
                bar_date = datetime.fromtimestamp(agg.timestamp / 1000, tz=timezone.utc).date()

                bars.append(DailyBar(
                    date=bar_date,
                    open=float(agg.open),
                    high=float(agg.high),
                    low=float(agg.low),
                    close=float(agg.close),
                    volume=int(agg.volume) if agg.volume else 0
                ))
            
            bars.sort(key=lambda x: x.date)

            # Clean erroneous data (bad ticks, extreme wicks, negative prices)
            from canslim_monitor.utils.data_cleaner import clean_daily_bars
            bars = clean_daily_bars(bars)

            logger.info(f"Fetched {len(bars)} daily bars for {polygon_symbol} from Polygon")
            return bars
            
        except Exception as e:
            logger.error(f"Error fetching {polygon_symbol} from Polygon: {e}")
            raise
    
    def get_multiple_symbols(
        self,
        symbols: List[str],
        lookback_days: int = 35,
        end_date: date = None
    ) -> Dict[str, List[DailyBar]]:
        """Fetch daily bars for multiple symbols."""
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_daily_bars(symbol, lookback_days, end_date)
            except Exception as e:
                logger.error(f"Failed to fetch {symbol}: {e}")
                results[symbol] = []
        return results


class TradingCalendar:
    """Simple trading calendar for NYSE/NASDAQ."""
    
    def __init__(self):
        self.calendar = None
        try:
            import exchange_calendars as xcals
            self.calendar = xcals.get_calendar('XNYS')
            logger.info("Using exchange_calendars for trading day detection")
        except ImportError:
            logger.warning("exchange_calendars not installed. Using basic weekend check.")
    
    def is_trading_day(self, check_date: date) -> bool:
        """Check if a date is a trading day."""
        if self.calendar:
            import pandas as pd
            return self.calendar.is_session(pd.Timestamp(check_date))
        else:
            return check_date.weekday() < 5
    
    def get_trading_days_back(self, from_date: date, count: int) -> List[date]:
        """Get the last N trading days before (and including) from_date."""
        days = []
        current = from_date
        
        while len(days) < count:
            if self.is_trading_day(current):
                days.append(current)
            current -= timedelta(days=1)
        
        return list(reversed(days))
    
    def trading_days_between(self, start_date: date, end_date: date) -> int:
        """Count trading days between two dates."""
        count = 0
        current = start_date
        
        while current <= end_date:
            if self.is_trading_day(current):
                count += 1
            current += timedelta(days=1)
        
        return count


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def fetch_index_daily(
    symbols: List[str] = None,
    lookback_days: int = 35,
    config: dict = None,
    use_indices: bool = True,
    end_date: date = None
) -> Dict[str, List[DailyBar]]:
    """
    Fetch daily bars for market indices/ETFs.

    Args:
        symbols: List of symbols (default: SPX and COMP if use_indices, else SPY and QQQ)
        lookback_days: Calendar days to fetch
        config: Config dict with API key
        use_indices: If True, use actual indices (SPX, COMP). If False, use ETFs (SPY, QQQ)
        end_date: End date for data (default: today)

    Returns:
        Dict mapping symbol -> list of DailyBar
    """
    if symbols is None:
        if use_indices:
            symbols = ['SPX', 'COMP']
        else:
            symbols = ['SPY', 'QQQ']

    if config:
        client = MassiveHistoricalClient.from_config(config)
    else:
        client = MassiveHistoricalClient()

    return client.get_multiple_symbols(symbols, lookback_days, end_date)


def fetch_spy_qqq_daily(
    lookback_days: int = 35,
    config: dict = None,
    use_indices: bool = False,
    end_date: date = None
) -> Dict[str, List[DailyBar]]:
    """
    Backward-compatible function to fetch SPY/QQQ or SPX/COMP data.

    Args:
        lookback_days: Number of calendar days to fetch
        config: Config dict with API key
        use_indices: If True, fetch SPX/COMP. If False, fetch SPY/QQQ (default)
        end_date: End date for data (default: today)

    Returns:
        Dict with keys 'SPY' and 'QQQ' (or 'SPX' and 'COMP')
    """
    logger.info(f"fetch_spy_qqq_daily called with use_indices={use_indices}")

    if use_indices:
        logger.info("Using actual indices: SPX (S&P 500) and COMP (Nasdaq Composite)")
        data = fetch_index_daily(['SPX', 'COMP'], lookback_days, config, use_indices=True, end_date=end_date)
        # Remap keys for backward compatibility
        return {
            'SPY': data.get('SPX', []),
            'QQQ': data.get('COMP', [])
        }
    else:
        logger.info("Using ETFs: SPY and QQQ")
        return fetch_index_daily(['SPY', 'QQQ'], lookback_days, config, use_indices=False, end_date=end_date)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Historical Data Client with Index Support")
    print("=" * 60)
    
    # Test fetching actual indices
    print("\n1. Fetching actual indices (SPX, COMP)...")
    try:
        data = fetch_index_daily(['SPX', 'COMP'], lookback_days=35, use_indices=True)
        
        for symbol, bars in data.items():
            print(f"\n{symbol}: {len(bars)} bars")
            if bars:
                print(f"  First: {bars[0].date} Close: ${bars[0].close:.2f} Vol: {bars[0].volume:,}")
                print(f"  Last:  {bars[-1].date} Close: ${bars[-1].close:.2f} Vol: {bars[-1].volume:,}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test backward compatible function
    print("\n2. Testing backward-compatible fetch_spy_qqq_daily()...")
    try:
        data = fetch_spy_qqq_daily(lookback_days=35, use_indices=True)
        print(f"Keys returned: {list(data.keys())}")
        for symbol, bars in data.items():
            if bars:
                print(f"  {symbol}: {len(bars)} bars, last close: ${bars[-1].close:.2f}")
    except Exception as e:
        print(f"Error: {e}")
