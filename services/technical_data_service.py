"""
CANSLIM Monitor - Technical Data Service
=========================================
Fetches and caches technical indicators (MAs, volume) for position monitoring.

Uses Polygon API for historical data, caches results to minimize API calls.
Data is refreshed once per day since Polygon free tier is 1-day delayed.

Usage:
    service = TechnicalDataService(polygon_api_key="your_key")
    data = service.get_technical_data("NVDA")
    # Returns: {'ma_21': 145.50, 'ma_50': 142.30, 'ma_200': 130.00, ...}
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import threading


@dataclass
class TechnicalData:
    """Technical indicators for a symbol."""
    symbol: str
    as_of_date: date
    
    # Moving averages
    ma_21: Optional[float] = None
    ma_50: Optional[float] = None
    ma_200: Optional[float] = None
    ma_10_week: Optional[float] = None
    ema_21: Optional[float] = None
    
    # Volume
    avg_volume_50d: Optional[int] = None
    last_close: Optional[float] = None
    
    # Metadata
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ma_21': self.ma_21,
            'ma_50': self.ma_50,
            'ma_200': self.ma_200,
            'ma_10_week': self.ma_10_week,
            'ema_21': self.ema_21,
            'avg_volume_50d': self.avg_volume_50d,
            'last_close': self.last_close,
        }


class TechnicalDataService:
    """
    Service for fetching and caching technical data.
    
    Features:
    - Fetches daily bars from Polygon API
    - Calculates MAs (21, 50, 200 daily + 10-week)
    - Caches data for the day (refreshes once per day)
    - Thread-safe for concurrent access
    """
    
    def __init__(
        self,
        polygon_api_key: str = None,
        cache_duration_hours: int = 4,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the service.
        
        Args:
            polygon_api_key: Polygon.io API key
            cache_duration_hours: How long to cache data (default 4 hours)
            logger: Logger instance
        """
        self.api_key = polygon_api_key
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.logger = logger or logging.getLogger('canslim.technical_data')
        
        # Cache: symbol -> TechnicalData
        self._cache: Dict[str, TechnicalData] = {}
        self._cache_lock = threading.Lock()
        
        # Polygon client (lazy init)
        self._polygon_client = None
    
    @property
    def polygon_client(self):
        """Lazy-initialize Polygon client."""
        if self._polygon_client is None and self.api_key:
            try:
                from canslim_monitor.integrations.polygon_client import PolygonClient
                self._polygon_client = PolygonClient(
                    api_key=self.api_key,
                    logger=self.logger
                )
            except ImportError:
                self.logger.warning("PolygonClient not available")
        return self._polygon_client
    
    def get_technical_data(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get technical data for a symbol.
        
        Returns cached data if fresh, otherwise fetches from Polygon.
        
        Args:
            symbol: Stock symbol
            force_refresh: Force fetch even if cached
            
        Returns:
            Dict with ma_21, ma_50, ma_200, ma_10_week, avg_volume_50d, etc.
        """
        symbol = symbol.upper()
        
        # Check cache
        with self._cache_lock:
            cached = self._cache.get(symbol)
            if cached and not force_refresh:
                age = datetime.now() - cached.fetched_at
                if age < self.cache_duration:
                    self.logger.debug(f"{symbol}: Using cached data (age: {age})")
                    return cached.to_dict()
        
        # Fetch fresh data
        data = self._fetch_technical_data(symbol)
        
        # Update cache
        with self._cache_lock:
            self._cache[symbol] = data
        
        return data.to_dict()
    
    def get_multiple(self, symbols: List[str], force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Get technical data for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            force_refresh: Force fetch for all
            
        Returns:
            Dict mapping symbol to technical data dict
        """
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_technical_data(symbol, force_refresh)
            except Exception as e:
                self.logger.error(f"Error fetching {symbol}: {e}")
                results[symbol] = {}
        return results
    
    def _fetch_technical_data(self, symbol: str) -> TechnicalData:
        """
        Fetch fresh technical data from Polygon.
        
        Fetches 250 daily bars to calculate:
        - 21-day SMA and EMA
        - 50-day SMA
        - 200-day SMA
        - 10-week SMA (from weekly aggregation)
        - 50-day average volume
        """
        today = date.today()
        
        if not self.polygon_client:
            self.logger.warning(f"{symbol}: No Polygon client, returning empty data")
            return TechnicalData(symbol=symbol, as_of_date=today)
        
        try:
            # Fetch 250 daily bars (need 200+ for 200-day MA)
            bars = self.polygon_client.get_daily_bars(symbol, days=250)
            
            if not bars or len(bars) < 21:
                self.logger.warning(f"{symbol}: Insufficient data ({len(bars) if bars else 0} bars)")
                return TechnicalData(symbol=symbol, as_of_date=today)
            
            # Extract close prices and volumes
            closes = [b.close for b in bars]
            volumes = [b.volume for b in bars]
            
            # Calculate MAs
            ma_21 = self._calculate_sma(closes, 21)
            ma_50 = self._calculate_sma(closes, 50) if len(closes) >= 50 else None
            ma_200 = self._calculate_sma(closes, 200) if len(closes) >= 200 else None
            ema_21 = self._calculate_ema(closes, 21)
            
            # Calculate 10-week MA from weekly data
            ma_10_week = self._calculate_weekly_ma(bars, 10)
            
            # Calculate average volume
            avg_volume = self._calculate_avg_volume(volumes, 50)
            
            # Last close
            last_close = closes[-1] if closes else None
            as_of_date = bars[-1].bar_date if bars else today
            
            data = TechnicalData(
                symbol=symbol,
                as_of_date=as_of_date,
                ma_21=round(ma_21, 2) if ma_21 else None,
                ma_50=round(ma_50, 2) if ma_50 else None,
                ma_200=round(ma_200, 2) if ma_200 else None,
                ma_10_week=round(ma_10_week, 2) if ma_10_week else None,
                ema_21=round(ema_21, 2) if ema_21 else None,
                avg_volume_50d=avg_volume,
                last_close=round(last_close, 2) if last_close else None,
            )
            
            self.logger.debug(
                f"{symbol}: MA21={data.ma_21}, MA50={data.ma_50}, "
                f"MA200={data.ma_200}, 10W={data.ma_10_week}"
            )
            
            return data
            
        except Exception as e:
            self.logger.error(f"{symbol}: Error fetching data: {e}")
            return TechnicalData(symbol=symbol, as_of_date=today)
    
    def _calculate_sma(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Simple Moving Average."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_weekly_ma(self, daily_bars: List, weeks: int) -> Optional[float]:
        """
        Calculate weekly moving average from daily bars.
        
        Aggregates to weekly closes, then calculates SMA.
        """
        if len(daily_bars) < weeks * 5:  # Need ~5 trading days per week
            return None
        
        # Group by week and get last close of each week
        weekly_closes = []
        current_week = None
        current_close = None
        
        for bar in daily_bars:
            bar_week = bar.bar_date.isocalendar()[1]  # Week number
            bar_year = bar.bar_date.year
            week_key = (bar_year, bar_week)
            
            if current_week != week_key:
                if current_close is not None:
                    weekly_closes.append(current_close)
                current_week = week_key
            
            current_close = bar.close
        
        # Don't forget the last week
        if current_close is not None:
            weekly_closes.append(current_close)
        
        if len(weekly_closes) < weeks:
            return None
        
        return sum(weekly_closes[-weeks:]) / weeks
    
    def _calculate_avg_volume(self, volumes: List[int], days: int) -> Optional[int]:
        """Calculate average volume over N days."""
        if len(volumes) < days:
            return int(sum(volumes) / len(volumes)) if volumes else None
        return int(sum(volumes[-days:]) / days)
    
    def calculate_volume_ratio(
        self,
        symbol: str,
        current_volume: int,
        use_time_adjusted: bool = True
    ) -> float:
        """
        Calculate volume ratio (current / average).
        
        Args:
            symbol: Stock symbol
            current_volume: Today's volume so far
            use_time_adjusted: Adjust for time of day (intraday)
            
        Returns:
            Volume ratio (1.0 = average, 1.5 = 50% above average)
        """
        data = self.get_technical_data(symbol)
        avg_volume = data.get('avg_volume_50d')
        
        if not avg_volume or avg_volume == 0:
            return 1.0
        
        if use_time_adjusted:
            # Adjust for time of day
            # Market hours: 9:30 AM - 4:00 PM ET (6.5 hours)
            now = datetime.now()
            market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
            
            if now < market_open:
                # Pre-market, can't calculate meaningful ratio
                return 1.0
            elif now > market_close:
                # After hours, use full day comparison
                time_factor = 1.0
            else:
                # Intraday - calculate what portion of day has elapsed
                total_minutes = 6.5 * 60  # 390 minutes
                elapsed_minutes = (now - market_open).total_seconds() / 60
                time_factor = elapsed_minutes / total_minutes
                time_factor = max(0.1, min(1.0, time_factor))  # Clamp to 0.1-1.0
            
            # Expected volume at this time = avg * time_factor
            expected_volume = avg_volume * time_factor
            
            if expected_volume > 0:
                return current_volume / expected_volume
        
        # Simple ratio (for EOD or non-time-adjusted)
        return current_volume / avg_volume
    
    def clear_cache(self, symbol: str = None):
        """Clear cached data."""
        with self._cache_lock:
            if symbol:
                self._cache.pop(symbol.upper(), None)
            else:
                self._cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            return {
                'cached_symbols': len(self._cache),
                'symbols': list(self._cache.keys()),
            }


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the TechnicalDataService."""
    import os
    
    print("=" * 60)
    print("TECHNICAL DATA SERVICE TEST")
    print("=" * 60)
    
    # Get API key
    api_key = os.environ.get('POLYGON_API_KEY', '')
    if not api_key:
        api_key = input("Enter Polygon API key: ").strip()
    
    if not api_key:
        print("No API key provided")
        return
    
    # Create service
    logging.basicConfig(level=logging.DEBUG)
    service = TechnicalDataService(polygon_api_key=api_key)
    
    # Test single symbol
    print("\n1. Testing NVDA...")
    data = service.get_technical_data("NVDA")
    print(f"   MA21: ${data.get('ma_21')}")
    print(f"   MA50: ${data.get('ma_50')}")
    print(f"   MA200: ${data.get('ma_200')}")
    print(f"   10-Week: ${data.get('ma_10_week')}")
    print(f"   Avg Vol: {data.get('avg_volume_50d'):,}" if data.get('avg_volume_50d') else "   Avg Vol: N/A")
    
    # Test cache
    print("\n2. Testing cache (should be instant)...")
    import time
    start = time.time()
    data2 = service.get_technical_data("NVDA")
    elapsed = time.time() - start
    print(f"   Cached fetch: {elapsed*1000:.1f}ms")
    
    # Test multiple
    print("\n3. Testing multiple symbols...")
    symbols = ["AAPL", "MSFT", "GOOGL"]
    results = service.get_multiple(symbols)
    for sym, data in results.items():
        ma50 = data.get('ma_50', 'N/A')
        print(f"   {sym}: MA50=${ma50}")
    
    # Volume ratio test
    print("\n4. Testing volume ratio...")
    ratio = service.calculate_volume_ratio("NVDA", 50_000_000)
    print(f"   Volume ratio (50M volume): {ratio:.2f}x average")
    
    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
