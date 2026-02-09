"""
CANSLIM Monitor - IBKR Client
Interactive Brokers TWS/Gateway integration for real-time market data.

Uses ib_insync library for async IB API communication.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable
from threading import Lock, Thread
import time

try:
    from ib_insync import IB, Stock, Index, Contract, Ticker, util
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    IB = None


class IBKRClient:
    """
    Interactive Brokers client for real-time market data.
    
    Features:
    - Real-time quotes via TWS/Gateway
    - Quote caching to minimize API calls
    - Automatic reconnection
    - Moving average data from historical bars
    """
    
    # Default connection settings
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_PORT = 7497  # TWS paper trading (7496 for live)
    DEFAULT_CLIENT_ID = 10
    
    # Symbols that need Index contracts (not Stock)
    INDEX_SYMBOLS = {'VIX': ('VIX', 'CBOE', 'USD')}

    # Cache settings
    QUOTE_CACHE_SECONDS = 5
    HISTORICAL_CACHE_SECONDS = 300  # 5 minutes
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        client_id: int = None,
        logger: Optional[logging.Logger] = None,
        on_error: Optional[Callable] = None
    ):
        """
        Initialize IBKR client.
        
        Args:
            host: TWS/Gateway host (default: 127.0.0.1)
            port: TWS/Gateway port (default: 7497)
            client_id: Client ID for connection (default: 10)
            logger: Logger instance
            on_error: Error callback function
        """
        if not IB_AVAILABLE:
            raise ImportError("ib_insync not installed. Run: pip install ib_insync")
        
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.client_id = client_id or self.DEFAULT_CLIENT_ID
        self.logger = logger or logging.getLogger('canslim.ibkr')
        self.on_error = on_error
        
        # IB connection
        self._ib: Optional[IB] = None
        self._connected = False
        self._lock = Lock()
        
        # Caches
        self._quote_cache: Dict[str, Dict] = {}
        self._quote_cache_time: Dict[str, datetime] = {}
        self._historical_cache: Dict[str, Dict] = {}
        self._historical_cache_time: Dict[str, datetime] = {}
        
        # Subscribed tickers
        self._subscriptions: Dict[str, Ticker] = {}
    
    # ==================== CONNECTION ====================
    
    def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect to TWS/Gateway.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully
        """
        with self._lock:
            if self._connected:
                return True
            
            try:
                self._ib = IB()
                self._ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id,
                    timeout=timeout
                )
                
                self._connected = True
                self.logger.info(f"Connected to IBKR at {self.host}:{self.port}")
                
                # Set up error handler
                self._ib.errorEvent += self._on_ib_error
                
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to connect to IBKR: {e}")
                self._connected = False
                return False
    
    def disconnect(self):
        """Disconnect from TWS/Gateway."""
        with self._lock:
            if self._ib and self._connected:
                try:
                    # Cancel all subscriptions
                    for ticker in self._subscriptions.values():
                        self._ib.cancelMktData(ticker.contract)
                    self._subscriptions.clear()
                    
                    self._ib.disconnect()
                    self.logger.info("Disconnected from IBKR")
                except Exception as e:
                    self.logger.error(f"Error disconnecting: {e}")
                finally:
                    self._connected = False
                    self._ib = None
    
    def is_connected(self) -> bool:
        """Check if connected to TWS/Gateway."""
        return self._connected and self._ib is not None and self._ib.isConnected()
    
    def reconnect(self) -> bool:
        """Reconnect to TWS/Gateway."""
        self.disconnect()
        time.sleep(1)
        return self.connect()
    
    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        """Handle IB API errors."""
        # Filter out non-critical messages
        if errorCode in (2104, 2106, 2158):  # Market data farm messages
            return
        
        self.logger.warning(f"IBKR Error {errorCode}: {errorString}")
        
        if self.on_error:
            self.on_error(errorCode, errorString)
    
    # ==================== QUOTES ====================

    def _create_contract(self, symbol: str):
        """Create the appropriate contract type for a symbol."""
        if symbol.upper() in self.INDEX_SYMBOLS:
            sym, exchange, currency = self.INDEX_SYMBOLS[symbol.upper()]
            return Index(sym, exchange, currency)
        return Stock(symbol, 'SMART', 'USD')

    def get_quote(self, symbol: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get real-time quote for a symbol.
        
        Args:
            symbol: Stock symbol
            use_cache: Whether to use cached data
            
        Returns:
            Quote dict with price, volume, bid/ask data
        """
        if not self.is_connected():
            self.logger.warning("Not connected to IBKR")
            return None
        
        # Check cache
        if use_cache and symbol in self._quote_cache:
            cache_time = self._quote_cache_time.get(symbol)
            if cache_time:
                elapsed = (datetime.now() - cache_time).total_seconds()
                if elapsed < self.QUOTE_CACHE_SECONDS:
                    return self._quote_cache[symbol]
        
        try:
            # Create contract (handles VIX as Index, others as Stock)
            contract = self._create_contract(symbol)

            # Get snapshot
            self._ib.qualifyContracts(contract)
            ticker = self._ib.reqMktData(contract, '', True, False)
            self._ib.sleep(1)  # Wait for data
            
            # Build quote dict
            quote = self._ticker_to_quote(ticker, symbol)
            
            # Cache it
            self._quote_cache[symbol] = quote
            self._quote_cache_time[symbol] = datetime.now()
            
            return quote
            
        except Exception as e:
            self.logger.error(f"Error getting quote for {symbol}: {e}")
            return None
    
    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get quotes for multiple symbols.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dict mapping symbol to quote data
        """
        results = {}
        
        for symbol in symbols:
            quote = self.get_quote(symbol)
            if quote:
                results[symbol] = quote
        
        return results
    
    def subscribe(self, symbol: str, callback: Optional[Callable] = None) -> bool:
        """
        Subscribe to real-time updates for a symbol.
        
        Args:
            symbol: Stock symbol
            callback: Optional callback for updates
            
        Returns:
            True if subscribed successfully
        """
        if not self.is_connected():
            return False
        
        if symbol in self._subscriptions:
            return True  # Already subscribed
        
        try:
            contract = self._create_contract(symbol)
            self._ib.qualifyContracts(contract)

            ticker = self._ib.reqMktData(contract, '', False, False)
            self._subscriptions[symbol] = ticker
            
            if callback:
                ticker.updateEvent += lambda t: callback(self._ticker_to_quote(t, symbol))
            
            self.logger.debug(f"Subscribed to {symbol}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol}: {e}")
            return False
    
    def unsubscribe(self, symbol: str):
        """Unsubscribe from real-time updates."""
        if symbol in self._subscriptions:
            ticker = self._subscriptions.pop(symbol)
            if self._ib:
                self._ib.cancelMktData(ticker.contract)
            self.logger.debug(f"Unsubscribed from {symbol}")
    
    def _ticker_to_quote(self, ticker: 'Ticker', symbol: str) -> Dict:
        """Convert IB Ticker to quote dict."""
        # Handle NaN values
        def safe_float(val, default=0.0):
            if val is None or (isinstance(val, float) and val != val):  # NaN check
                return default
            return float(val)
        
        last = safe_float(ticker.last) or safe_float(ticker.close)
        
        return {
            'symbol': symbol,
            'last': last,
            'bid': safe_float(ticker.bid),
            'ask': safe_float(ticker.ask),
            'bid_size': safe_float(ticker.bidSize),
            'ask_size': safe_float(ticker.askSize),
            'volume': int(safe_float(ticker.volume)),
            'avg_volume': int(safe_float(ticker.avVolume)),
            'open': safe_float(ticker.open),
            'high': safe_float(ticker.high),
            'low': safe_float(ticker.low),
            'close': safe_float(ticker.close),
            'prev_close': safe_float(ticker.close),  # Will update with historical
            'timestamp': datetime.now().isoformat(),
        }
    
    # ==================== HISTORICAL DATA ====================
    
    def get_historical_data(
        self,
        symbol: str,
        duration: str = '65 D',
        bar_size: str = '1 day',
        use_cache: bool = True
    ) -> Optional[List[Dict]]:
        """
        Get historical bar data.
        
        Args:
            symbol: Stock symbol
            duration: Duration string (e.g., '65 D', '1 Y')
            bar_size: Bar size (e.g., '1 day', '1 hour')
            use_cache: Whether to use cached data
            
        Returns:
            List of bar dicts with OHLCV data
        """
        if not self.is_connected():
            return None
        
        cache_key = f"{symbol}_{duration}_{bar_size}"
        
        # Check cache
        if use_cache and cache_key in self._historical_cache:
            cache_time = self._historical_cache_time.get(cache_key)
            if cache_time:
                elapsed = (datetime.now() - cache_time).total_seconds()
                if elapsed < self.HISTORICAL_CACHE_SECONDS:
                    return self._historical_cache[cache_key]
        
        try:
            contract = self._create_contract(symbol)
            self._ib.qualifyContracts(contract)

            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                return None
            
            result = [
                {
                    'date': bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': int(bar.volume),
                }
                for bar in bars
            ]
            
            # Cache it
            self._historical_cache[cache_key] = result
            self._historical_cache_time[cache_key] = datetime.now()
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting historical data for {symbol}: {e}")
            return None
    
    def get_moving_averages(self, symbol: str) -> Optional[Dict]:
        """
        Calculate moving averages for a symbol.
        
        Returns:
            Dict with ma21, ma50, ma200 values
        """
        bars = self.get_historical_data(symbol, duration='250 D', bar_size='1 day')
        
        if not bars or len(bars) < 200:
            return None
        
        closes = [bar['close'] for bar in bars]
        
        ma21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else None
        ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        
        return {
            'ma21': round(ma21, 2) if ma21 else None,
            'ma50': round(ma50, 2) if ma50 else None,
            'ma200': round(ma200, 2) if ma200 else None,
            'prev_close': closes[-2] if len(closes) >= 2 else closes[-1],
        }
    
    def get_quote_with_technicals(self, symbol: str) -> Optional[Dict]:
        """
        Get quote with moving averages included.
        
        Returns:
            Quote dict enriched with MA data
        """
        quote = self.get_quote(symbol)
        if not quote:
            return None
        
        ma_data = self.get_moving_averages(symbol)
        if ma_data:
            quote.update(ma_data)
            
            # Calculate volume ratio
            if quote.get('avg_volume') and quote.get('volume'):
                quote['volume_ratio'] = round(quote['volume'] / quote['avg_volume'], 2)
            else:
                quote['volume_ratio'] = 1.0
        
        return quote
    
    # ==================== INDEX DATA ====================
    
    def get_index_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get quote for an index ETF (SPY, QQQ, DIA).
        
        Returns:
            Index quote with additional calculations
        """
        quote = self.get_quote_with_technicals(symbol)
        if not quote:
            return None
        
        # Calculate daily change
        if quote.get('last') and quote.get('prev_close'):
            change = quote['last'] - quote['prev_close']
            change_pct = (change / quote['prev_close']) * 100
            quote['change'] = round(change, 2)
            quote['change_pct'] = round(change_pct, 2)
        
        return quote
    
    # ==================== UTILITY ====================
    
    def clear_cache(self):
        """Clear all cached data."""
        self._quote_cache.clear()
        self._quote_cache_time.clear()
        self._historical_cache.clear()
        self._historical_cache_time.clear()
    
    def get_subscribed_symbols(self) -> List[str]:
        """Get list of subscribed symbols."""
        return list(self._subscriptions.keys())
    
    def sleep(self, seconds: float):
        """Sleep while processing IB messages."""
        if self._ib:
            self._ib.sleep(seconds)
        else:
            time.sleep(seconds)


# Singleton instance
_client: Optional[IBKRClient] = None


def get_ibkr_client(
    host: str = None,
    port: int = None,
    client_id: int = None
) -> IBKRClient:
    """
    Get the singleton IBKR client instance.
    
    Args:
        host: TWS/Gateway host
        port: TWS/Gateway port
        client_id: Client ID
        
    Returns:
        IBKRClient instance
    """
    global _client
    
    if _client is None:
        _client = IBKRClient(host=host, port=port, client_id=client_id)
    
    return _client


def init_ibkr_client(
    host: str = '127.0.0.1',
    port: int = 7497,
    client_id: int = 10,
    auto_connect: bool = True
) -> IBKRClient:
    """
    Initialize and optionally connect to IBKR.
    
    Args:
        host: TWS/Gateway host
        port: TWS/Gateway port
        client_id: Client ID
        auto_connect: Whether to connect immediately
        
    Returns:
        IBKRClient instance
    """
    client = get_ibkr_client(host=host, port=port, client_id=client_id)
    
    if auto_connect:
        client.connect()
    
    return client
