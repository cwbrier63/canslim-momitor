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

        # Clean erroneous data (bad ticks, extreme wicks, negative prices)
        try:
            from canslim_monitor.utils.data_cleaner import clean_daily_bars
            bars = clean_daily_bars(bars)
        except Exception:
            pass  # Don't block data fetch if cleaner fails

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

        Tries multiple sources in order:
        1. Polygon ticker events endpoint
        2. Polygon ticker details endpoint
        3. Yahoo Finance (fallback - most reliable for earnings)

        Args:
            symbol: Stock symbol (e.g., "NVDA")

        Returns:
            Next earnings date or None if not found
        """
        symbol = symbol.upper()

        # Try Polygon ticker events endpoint first
        endpoint = f"/vX/reference/tickers/{symbol}/events"
        params = {'types': 'earnings', 'limit': 5}

        response = self._make_request(endpoint, params)

        if response and response.get('status') == 'OK':
            events = response.get('results', {}).get('events', [])
            today = date.today()

            for event in events:
                try:
                    event_date_str = event.get('date')
                    if event_date_str:
                        event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                        if event_date >= today:
                            self.logger.debug(f"{symbol}: Next earnings {event_date} (Polygon events)")
                            return event_date
                except Exception as e:
                    self.logger.warning(f"Error parsing earnings date for {symbol}: {e}")
                    continue

        # Fallback 1: Try Polygon ticker details endpoint
        endpoint = f"/v3/reference/tickers/{symbol}"
        response = self._make_request(endpoint)

        if response and response.get('status') == 'OK':
            results = response.get('results', {})
            earnings_str = results.get('next_earnings_date')
            if earnings_str:
                try:
                    earnings_date = datetime.strptime(earnings_str, '%Y-%m-%d').date()
                    self.logger.debug(f"{symbol}: Next earnings {earnings_date} (Polygon details)")
                    return earnings_date
                except Exception as e:
                    self.logger.warning(f"Error parsing earnings date for {symbol}: {e}")

        # Fallback 2: Try Yahoo Finance (most reliable for earnings)
        earnings_date = self._get_earnings_from_yahoo(symbol)
        if earnings_date:
            return earnings_date

        self.logger.debug(f"{symbol}: No earnings date found from any source")
        return None

    def _get_earnings_from_yahoo(self, symbol: str) -> Optional[date]:
        """
        Get next earnings date from Yahoo Finance.

        Args:
            symbol: Stock symbol

        Returns:
            Next earnings date or None if not found
        """
        try:
            import yfinance as yf
            from datetime import date as date_type

            self.logger.debug(f"{symbol}: Trying Yahoo Finance for earnings...")
            ticker = yf.Ticker(symbol)

            # Try earnings_dates attribute (most reliable)
            try:
                earnings_dates = ticker.earnings_dates
                if earnings_dates is not None and not earnings_dates.empty:
                    today = date_type.today()
                    # Filter for future dates
                    future_dates = earnings_dates[earnings_dates.index >= str(today)]
                    if not future_dates.empty:
                        next_date = future_dates.index[0]
                        # Convert to date object
                        if hasattr(next_date, 'date'):
                            result = next_date.date()
                        else:
                            result = datetime.strptime(str(next_date)[:10], '%Y-%m-%d').date()
                        self.logger.info(f"{symbol}: Next earnings {result} (Yahoo Finance)")
                        return result
            except Exception as e:
                self.logger.debug(f"{symbol}: Yahoo earnings_dates failed: {e}")

            # Fallback: Try calendar attribute
            try:
                calendar = ticker.calendar
                if calendar and isinstance(calendar, dict):
                    earnings_date = calendar.get('Earnings Date')
                    if earnings_date:
                        if isinstance(earnings_date, list) and earnings_date:
                            earnings_date = earnings_date[0]
                        if hasattr(earnings_date, 'date'):
                            result = earnings_date.date()
                        else:
                            result = datetime.strptime(str(earnings_date)[:10], '%Y-%m-%d').date()
                        self.logger.info(f"{symbol}: Next earnings {result} (Yahoo calendar)")
                        return result
            except Exception as e:
                self.logger.debug(f"{symbol}: Yahoo calendar failed: {e}")

        except ImportError:
            self.logger.warning("yfinance not installed - Yahoo Finance fallback unavailable")
        except Exception as e:
            self.logger.warning(f"{symbol}: Yahoo Finance lookup failed: {e}")

        return None
    
    def get_intraday_volume(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get today's cumulative intraday volume using minute aggregates.

        Requires Stocks Starter tier or higher for 15-min delayed intraday data.

        Args:
            symbol: Stock symbol (e.g., "NVDA")

        Returns:
            Dict with:
                - cumulative_volume: Total shares traded today
                - last_price: Most recent price
                - last_update: Timestamp of last bar
                - bars_count: Number of minute bars
            Returns None if data unavailable
        """
        symbol = symbol.upper()
        today = date.today()

        # Fetch today's minute bars
        endpoint = f"/v2/aggs/ticker/{symbol}/range/1/minute/{today.isoformat()}/{today.isoformat()}"

        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 500  # Should cover full trading day (390 minutes)
        }

        response = self._make_request(endpoint, params)

        if not response:
            self.logger.debug(f"{symbol}: No intraday data response")
            return None

        results = response.get('results', [])

        if not results:
            self.logger.debug(f"{symbol}: No intraday bars returned")
            return None

        # Calculate cumulative volume
        cumulative_volume = sum(r.get('v', 0) for r in results)

        # Get last bar info
        last_bar = results[-1]
        last_price = last_bar.get('c', 0)
        last_timestamp = datetime.fromtimestamp(last_bar['t'] / 1000) if 't' in last_bar else None

        self.logger.debug(
            f"{symbol}: Intraday volume={cumulative_volume:,}, "
            f"bars={len(results)}, last_price=${last_price:.2f}"
        )

        return {
            'symbol': symbol,
            'cumulative_volume': cumulative_volume,
            'last_price': last_price,
            'last_update': last_timestamp,
            'bars_count': len(results),
            'high': max(r.get('h', 0) for r in results),
            'low': min(r.get('l', float('inf')) for r in results if r.get('l', 0) > 0),
            'open': results[0].get('o', 0) if results else 0,
        }

    def get_intraday_volume_batch(self, symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get intraday volume for multiple symbols.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to intraday data (or None)
        """
        results = {}

        for i, symbol in enumerate(symbols):
            self.logger.debug(f"Fetching intraday volume for {symbol} ({i+1}/{len(symbols)})")
            intraday_data = self.get_intraday_volume(symbol)
            results[symbol] = intraday_data

        return results

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
