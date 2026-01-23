"""
CANSLIM Monitor - Polygon.io / Massive API Client
===================================================
Fetches historical OHLCV data for volume analysis.

Note: Data from Polygon free tier is 1-day delayed.
Massive.com resells Polygon data with same API format.

Usage:
    client = PolygonClient(api_key="your_key")
    bars = client.get_daily_bars("NVDA", days=50)
"""

import logging
import requests
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from time import sleep


@dataclass
class Bar:
    """Single OHLCV bar."""
    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    transactions: Optional[int] = None


class PolygonClient:
    """
    Polygon.io API client for historical market data.
    
    Compatible with:
    - Polygon.io (https://api.polygon.io)
    - Massive.com (uses same API format)
    
    Rate limits:
    - Free tier: 5 calls/minute
    - Paid tiers: Higher limits
    """
    
    DEFAULT_BASE_URL = "https://api.polygon.io"
    
    def __init__(
        self,
        api_key: str,
        base_url: str = None,
        timeout: int = 30,
        rate_limit_delay: float = 0.5,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Polygon client.
        
        Args:
            api_key: Polygon.io API key
            base_url: API base URL (default: https://api.polygon.io)
            timeout: Request timeout in seconds
            rate_limit_delay: Delay between requests to avoid rate limiting
            logger: Logger instance
        """
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.logger = logger or logging.getLogger('canslim.polygon')
        
        self._last_request_time = 0
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Make API request with rate limiting.
        
        Args:
            endpoint: API endpoint (e.g., /v2/aggs/ticker/AAPL/range/1/day/...)
            params: Query parameters
            
        Returns:
            JSON response dict or None on error
        """
        # Rate limiting
        now = datetime.now().timestamp()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            sleep(self.rate_limit_delay - elapsed)
        
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key
        
        try:
            self.logger.debug(f"Requesting: {endpoint}")
            response = requests.get(url, params=params, timeout=self.timeout)
            self._last_request_time = datetime.now().timestamp()
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                self.logger.warning("Rate limited by Polygon API")
                sleep(60)  # Wait a minute on rate limit
                return None
            elif response.status_code == 403:
                self.logger.error("Invalid API key or unauthorized access")
                return None
            else:
                self.logger.error(f"API error {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            self.logger.error(f"Request timeout: {endpoint}")
            return None
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            return None
    
    def get_daily_bars(
        self,
        symbol: str,
        days: int = 50,
        end_date: date = None
    ) -> List[Bar]:
        """
        Get daily OHLCV bars for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "NVDA")
            days: Number of trading days to fetch (default 50)
            end_date: End date (default: yesterday due to 1-day delay)
            
        Returns:
            List of Bar objects, oldest first
        """
        # Default end date is yesterday (Polygon free tier is 1-day delayed)
        if end_date is None:
            end_date = date.today() - timedelta(days=1)
        
        # Start date: go back extra days to account for weekends/holidays
        start_date = end_date - timedelta(days=int(days * 1.5) + 10)
        
        endpoint = f"/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}"
        
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': days + 20  # Get a few extra in case of holidays
        }
        
        response = self._make_request(endpoint, params)
        
        if not response:
            return []
        
        if response.get('status') != 'OK' and response.get('resultsCount', 0) == 0:
            self.logger.warning(f"No data returned for {symbol}")
            return []
        
        results = response.get('results', [])
        bars = []
        
        for r in results:
            try:
                # Polygon returns timestamp in milliseconds
                bar_date = datetime.fromtimestamp(r['t'] / 1000).date()
                
                bar = Bar(
                    symbol=symbol.upper(),
                    bar_date=bar_date,
                    open=r.get('o', 0),
                    high=r.get('h', 0),
                    low=r.get('l', 0),
                    close=r.get('c', 0),
                    volume=int(r.get('v', 0)),
                    vwap=r.get('vw'),
                    transactions=r.get('n')
                )
                bars.append(bar)
            except Exception as e:
                self.logger.warning(f"Error parsing bar for {symbol}: {e}")
                continue
        
        # Return only the requested number of days (most recent)
        if len(bars) > days:
            bars = bars[-days:]
        
        self.logger.debug(f"Fetched {len(bars)} bars for {symbol}")
        return bars
    
    def get_multiple_symbols(
        self,
        symbols: List[str],
        days: int = 50,
        end_date: date = None
    ) -> Dict[str, List[Bar]]:
        """
        Get daily bars for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            days: Number of trading days per symbol
            end_date: End date for all symbols
            
        Returns:
            Dict mapping symbol to list of bars
        """
        results = {}
        
        for i, symbol in enumerate(symbols):
            self.logger.info(f"Fetching {symbol} ({i+1}/{len(symbols)})")
            bars = self.get_daily_bars(symbol, days, end_date)
            results[symbol] = bars
            
            # Progress logging every 10 symbols
            if (i + 1) % 10 == 0:
                self.logger.info(f"Progress: {i+1}/{len(symbols)} symbols fetched")
        
        return results
    
    def calculate_average_volume(self, bars: List[Bar], days: int = 50) -> int:
        """
        Calculate average daily volume from bars.
        
        Args:
            bars: List of Bar objects
            days: Number of days to average (uses most recent N bars)
            
        Returns:
            Average volume as integer
        """
        if not bars:
            return 0
        
        # Use most recent N bars
        recent_bars = bars[-days:] if len(bars) > days else bars
        
        if not recent_bars:
            return 0
        
        total_volume = sum(b.volume for b in recent_bars)
        return int(total_volume / len(recent_bars))
    
    def test_connection(self) -> bool:
        """
        Test API connection with a simple request.
        
        Returns:
            True if connection successful
        """
        # Use a simple ticker details request to test
        endpoint = "/v3/reference/tickers/AAPL"
        response = self._make_request(endpoint)
        
        if response and response.get('status') == 'OK':
            self.logger.info("Polygon API connection successful")
            return True
        else:
            self.logger.error("Polygon API connection failed")
            return False
    
    def get_next_earnings_date(self, symbol: str) -> Optional[date]:
        """
        Get the next earnings date for a symbol.
        
        Uses Polygon's ticker events endpoint to find upcoming earnings.
        
        Args:
            symbol: Stock symbol (e.g., "NVDA")
            
        Returns:
            Next earnings date or None if not found
        """
        # Try ticker events endpoint first (more reliable for earnings)
        endpoint = f"/vX/reference/tickers/{symbol.upper()}/events"
        
        params = {
            'types': 'earnings',
            'limit': 5
        }
        
        response = self._make_request(endpoint, params)
        
        if response and response.get('status') == 'OK':
            events = response.get('results', {}).get('events', [])
            today = date.today()
            
            for event in events:
                try:
                    event_date_str = event.get('date')
                    if event_date_str:
                        event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                        # Return first future earnings date
                        if event_date >= today:
                            self.logger.debug(f"{symbol}: Next earnings {event_date}")
                            return event_date
                except Exception as e:
                    self.logger.warning(f"Error parsing earnings date for {symbol}: {e}")
                    continue
        
        # Fallback: Try ticker details endpoint
        endpoint = f"/v3/reference/tickers/{symbol.upper()}"
        response = self._make_request(endpoint)
        
        if response and response.get('status') == 'OK':
            results = response.get('results', {})
            
            # Check for next_earnings_date field
            earnings_str = results.get('next_earnings_date')
            if earnings_str:
                try:
                    earnings_date = datetime.strptime(earnings_str, '%Y-%m-%d').date()
                    self.logger.debug(f"{symbol}: Next earnings {earnings_date} (from ticker details)")
                    return earnings_date
                except Exception as e:
                    self.logger.warning(f"Error parsing earnings date for {symbol}: {e}")
        
        self.logger.debug(f"{symbol}: No earnings date found")
        return None
    
    def get_earnings_dates_batch(self, symbols: List[str]) -> Dict[str, Optional[date]]:
        """
        Get earnings dates for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dict mapping symbol to earnings date (or None)
        """
        results = {}
        
        for i, symbol in enumerate(symbols):
            self.logger.info(f"Looking up earnings for {symbol} ({i+1}/{len(symbols)})")
            earnings_date = self.get_next_earnings_date(symbol)
            results[symbol] = earnings_date
            
            # Progress logging every 10 symbols
            if (i + 1) % 10 == 0:
                self.logger.info(f"Progress: {i+1}/{len(symbols)} symbols checked")
        
        return results


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the Polygon client."""
    import os
    
    print("=" * 60)
    print("POLYGON CLIENT TEST")
    print("=" * 60)
    
    # Get API key from environment or prompt
    api_key = os.environ.get('POLYGON_API_KEY', '')
    if not api_key:
        api_key = input("Enter Polygon API key: ").strip()
    
    if not api_key:
        print("No API key provided")
        return
    
    client = PolygonClient(api_key=api_key)
    
    # Test connection
    print("\n1. Testing connection...")
    if not client.test_connection():
        print("Connection failed!")
        return
    
    # Test fetching bars
    print("\n2. Fetching 50-day bars for NVDA...")
    bars = client.get_daily_bars("NVDA", days=50)
    
    if bars:
        print(f"   Fetched {len(bars)} bars")
        print(f"   Date range: {bars[0].bar_date} to {bars[-1].bar_date}")
        print(f"   Latest close: ${bars[-1].close:.2f}")
        print(f"   Latest volume: {bars[-1].volume:,}")
        
        avg_vol = client.calculate_average_volume(bars)
        print(f"   50-day avg volume: {avg_vol:,}")
    else:
        print("   No bars returned")
    
    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
