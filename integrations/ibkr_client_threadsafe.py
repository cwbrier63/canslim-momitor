"""
CANSLIM Monitor - Thread-Safe IBKR Client with Auto-Reconnect
==============================================================
Wraps ib_insync to provide thread-safe access and automatic reconnection
after overnight IB Gateway restarts.

Key Features:
- Runs ib_insync in dedicated thread with its own event loop
- Automatic reconnection with exponential backoff
- Connection health monitoring
- Thread-safe price queries from any thread
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass


@dataclass
class ReconnectConfig:
    """Configuration for reconnection behavior."""
    enabled: bool = True
    initial_delay: float = 30.0     # First retry after 30 seconds (Gateway needs time to restart)
    max_delay: float = 300.0        # Max 5 minutes between retries
    backoff_factor: float = 1.5     # Slower backoff (1.5x instead of 2x)
    max_attempts: int = 0           # 0 = unlimited attempts
    health_check_interval: float = 30.0  # Check connection every 30 seconds
    gateway_restart_delay: float = 120.0  # Wait 2 minutes if overnight restart detected


class ThreadSafeIBKRClient:
    """
    Thread-safe IBKR client with automatic reconnection.
    
    Usage:
        client = ThreadSafeIBKRClient(host='127.0.0.1', port=4001, client_id=20)
        if client.connect():
            price = client.get_quote('AAPL')
    """
    
    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 4001,
        client_id: int = 1,
        logger: Optional[logging.Logger] = None,
        reconnect_config: Optional[ReconnectConfig] = None,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.logger = logger or logging.getLogger('canslim.service.ibkr')
        self.reconnect_config = reconnect_config or ReconnectConfig()
        
        # Callbacks for connection state changes
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        
        # IB connection (created in background thread)
        self._ib = None
        self._loop = None
        self._thread = None
        self._connected = threading.Event()
        self._shutdown = threading.Event()
        self._lock = threading.Lock()
        
        # Reconnection state
        self._reconnect_attempts = 0
        self._last_connect_time: Optional[datetime] = None
        self._last_disconnect_time: Optional[datetime] = None
        self._reconnecting = False
        
        # Health check timer
        self._health_check_timer = None
        
    def connect(self, timeout: float = 30.0) -> bool:
        """
        Connect to IB Gateway/TWS.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully
        """
        if self._connected.is_set():
            return True
            
        # Start background thread if not running
        if self._thread is None or not self._thread.is_alive():
            self._shutdown.clear()
            self._thread = threading.Thread(
                target=self._run_event_loop,
                name='IBKRClient',
                daemon=True
            )
            self._thread.start()
        
        # Wait for connection
        if self._connected.wait(timeout=timeout):
            self._last_connect_time = datetime.now()
            self._reconnect_attempts = 0
            self.logger.info(f"Connected to IBKR at {self.host}:{self.port}")
            
            # Start health check
            self._start_health_check()
            
            # Notify callback
            if self.on_connect:
                try:
                    self.on_connect()
                except Exception as e:
                    self.logger.warning(f"on_connect callback error: {e}")
            
            return True
        else:
            self.logger.error(f"Connection timeout after {timeout}s")
            return False
    
    def disconnect(self):
        """Disconnect from IB Gateway/TWS."""
        self._shutdown.set()
        self._stop_health_check()
        
        if self._ib and self._loop:
            try:
                # Schedule disconnect in the event loop
                asyncio.run_coroutine_threadsafe(
                    self._async_disconnect(),
                    self._loop
                ).result(timeout=5.0)
            except Exception as e:
                self.logger.debug(f"Disconnect error: {e}")
        
        self._connected.clear()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
    
    async def _async_disconnect(self):
        """Async disconnect helper."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
    
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._connected.is_set() and self._ib and self._ib.isConnected()
    
    def _run_event_loop(self):
        """Run the asyncio event loop in background thread."""
        try:
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Import ib_insync in the thread where it will be used
            from ib_insync import IB
            
            self._ib = IB()
            
            # Set up disconnect handler
            self._ib.disconnectedEvent += self._on_ib_disconnect
            
            # Initial connection
            self._loop.run_until_complete(self._async_connect())
            
            # Run event loop until shutdown
            while not self._shutdown.is_set():
                try:
                    # Process IB events
                    self._ib.sleep(0.1)
                except Exception as e:
                    if not self._shutdown.is_set():
                        self.logger.error(f"IB loop error: {e}")
                        self._handle_disconnect()
                        break
            
        except Exception as e:
            self.logger.error(f"Event loop error: {e}")
        finally:
            self._connected.clear()
            if self._loop:
                self._loop.close()
    
    async def _async_connect(self) -> bool:
        """Async connection helper."""
        try:
            await self._ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=True
            )
            
            if self._ib.isConnected():
                self._connected.set()
                self.logger.debug("IB connection established in background thread")
                return True
            else:
                self.logger.warning("IB connection failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def _on_ib_disconnect(self):
        """Handle IB disconnect event."""
        if not self._shutdown.is_set():
            self.logger.warning(
                "IBKR disconnected unexpectedly - "
                "likely IB Gateway nightly restart or network issue"
            )
            self._handle_disconnect()

    def _handle_disconnect(self):
        """Handle disconnect and trigger reconnection."""
        was_connected = self._connected.is_set()
        self._connected.clear()
        self._last_disconnect_time = datetime.now()

        self.logger.info(
            f"Connection state changed: connected={was_connected} -> disconnected, "
            f"reconnect_enabled={self.reconnect_config.enabled}, "
            f"shutdown_requested={self._shutdown.is_set()}"
        )

        # Notify callback
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception as e:
                self.logger.warning(f"on_disconnect callback error: {e}")

        # Trigger reconnection if enabled
        if self.reconnect_config.enabled and not self._shutdown.is_set():
            self.logger.info("Scheduling automatic reconnection...")
            self._schedule_reconnect()
        else:
            self.logger.warning(
                f"Auto-reconnect NOT triggered: enabled={self.reconnect_config.enabled}, "
                f"shutdown={self._shutdown.is_set()}"
            )
    
    def _schedule_reconnect(self):
        """Schedule a reconnection attempt."""
        if self._reconnecting or self._shutdown.is_set():
            return

        self._reconnecting = True

        # Detect if this is likely an overnight Gateway restart (between midnight and 3 AM)
        current_hour = datetime.now().hour
        is_overnight_restart = 0 <= current_hour <= 3

        # Calculate delay
        if is_overnight_restart and self._reconnect_attempts == 0:
            # First attempt during overnight window - use gateway restart delay
            delay = self.reconnect_config.gateway_restart_delay
            self.logger.info(
                f"Overnight Gateway restart detected (hour={current_hour}). "
                f"Waiting {delay:.0f}s for Gateway to fully restart..."
            )
        else:
            # Normal exponential backoff
            delay = min(
                self.reconnect_config.initial_delay * (
                    self.reconnect_config.backoff_factor ** self._reconnect_attempts
                ),
                self.reconnect_config.max_delay
            )

        self._reconnect_attempts += 1

        # Check max attempts (0 = unlimited)
        if (self.reconnect_config.max_attempts > 0 and
            self._reconnect_attempts > self.reconnect_config.max_attempts):
            self.logger.error(
                f"Max reconnection attempts ({self.reconnect_config.max_attempts}) exceeded. "
                f"Will continue health checks and retry on next disconnect detection."
            )
            self._reconnecting = False
            # Reset attempts so health check can trigger new reconnection cycle
            self._reconnect_attempts = 0
            return

        self.logger.info(
            f"Scheduling reconnection attempt {self._reconnect_attempts} "
            f"in {delay:.1f}s (overnight={is_overnight_restart})"
        )

        # Start reconnection in new thread
        reconnect_thread = threading.Thread(
            target=self._do_reconnect,
            args=(delay,),
            name='IBKRReconnect',
            daemon=True
        )
        reconnect_thread.start()
    
    def _do_reconnect(self, delay: float):
        """Perform reconnection after delay."""
        try:
            self.logger.info(f"Waiting {delay:.1f}s before reconnection attempt...")

            # Wait for delay (but check shutdown periodically and log progress)
            wait_start = time.time()
            last_log_time = wait_start
            while time.time() - wait_start < delay:
                if self._shutdown.is_set():
                    self.logger.info("Reconnection cancelled - shutdown requested")
                    self._reconnecting = False
                    return
                time.sleep(0.5)

                # Log progress every 30 seconds during long waits
                elapsed = time.time() - wait_start
                if time.time() - last_log_time >= 30.0:
                    remaining = delay - elapsed
                    self.logger.info(f"Still waiting for Gateway... {remaining:.0f}s remaining")
                    last_log_time = time.time()

            if self._shutdown.is_set():
                self.logger.info("Reconnection cancelled - shutdown requested")
                self._reconnecting = False
                return

            self.logger.info(
                f"Attempting reconnection to {self.host}:{self.port} "
                f"(attempt {self._reconnect_attempts}, client_id={self.client_id})..."
            )

            # Stop old thread if running - ensure clean disconnection first
            if self._thread and self._thread.is_alive():
                self.logger.info("Stopping old IB connection...")

                # First, explicitly disconnect from Gateway if IB object exists
                if self._ib and self._loop and self._loop.is_running():
                    try:
                        self.logger.debug("Explicitly disconnecting from Gateway...")
                        future = asyncio.run_coroutine_threadsafe(
                            self._async_disconnect(),
                            self._loop
                        )
                        future.result(timeout=5.0)
                        self.logger.debug("Disconnect request sent to Gateway")
                    except Exception as e:
                        self.logger.debug(f"Disconnect request error (may be expected): {e}")

                # Now signal thread shutdown and wait
                self._shutdown.set()
                self._thread.join(timeout=10.0)  # Increased timeout
                if self._thread.is_alive():
                    self.logger.warning("Old IB thread did not stop cleanly")

                # Wait for Gateway to process disconnect before reconnecting
                self.logger.debug("Waiting 5s for Gateway to process disconnect...")
                time.sleep(5.0)

                self._shutdown.clear()

            # Clear old IB reference to ensure fresh start
            self._ib = None
            self._loop = None

            # Start fresh connection
            self.logger.debug("Starting new IB thread...")
            self._thread = threading.Thread(
                target=self._run_event_loop,
                name='IBKRClient',
                daemon=True
            )
            self._thread.start()

            # Wait for connection
            self.logger.debug("Waiting for connection to establish...")
            if self._connected.wait(timeout=30.0):
                self._reconnect_attempts = 0
                self._last_connect_time = datetime.now()
                self.logger.info(
                    f"Reconnection successful! Connected to {self.host}:{self.port}"
                )

                # Restart health check
                self._start_health_check()

                # Notify callback
                if self.on_connect:
                    try:
                        self.on_connect()
                    except Exception as e:
                        self.logger.warning(f"on_connect callback error: {e}")
            else:
                self.logger.warning(
                    f"Reconnection attempt {self._reconnect_attempts} failed - "
                    f"connection timeout (30s). Will retry..."
                )
                # Schedule another attempt
                self._schedule_reconnect()

        except Exception as e:
            self.logger.error(f"Reconnection error: {e}", exc_info=True)
            self._schedule_reconnect()
        finally:
            self._reconnecting = False
    
    def _start_health_check(self):
        """Start periodic health check timer with active heartbeat."""
        if not self.reconnect_config.enabled:
            return

        self._stop_health_check()

        def check_health():
            consecutive_failures = 0
            max_failures = 3  # Trigger reconnect after 3 consecutive failures

            self.logger.info(
                f"Health check started (interval={self.reconnect_config.health_check_interval}s)"
            )

            while not self._shutdown.is_set():
                time.sleep(self.reconnect_config.health_check_interval)

                if self._shutdown.is_set():
                    break

                # Basic connection check
                if not self._ib or not self._ib.isConnected():
                    self.logger.warning("Health check: isConnected() returned False")
                    consecutive_failures = max_failures  # Immediate reconnect
                else:
                    # Active heartbeat - try to get server time
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self._async_heartbeat(),
                            self._loop
                        )
                        result = future.result(timeout=10.0)

                        if result:
                            consecutive_failures = 0  # Reset on success
                            self.logger.debug(f"Health check OK (server time: {result})")
                        else:
                            consecutive_failures += 1
                            self.logger.warning(
                                f"Health check: heartbeat failed ({consecutive_failures}/{max_failures})"
                            )
                    except Exception as e:
                        consecutive_failures += 1
                        self.logger.warning(
                            f"Health check: heartbeat error ({consecutive_failures}/{max_failures}): {e}"
                        )

                # Trigger reconnect if too many failures
                if consecutive_failures >= max_failures:
                    self.logger.error(
                        f"Health check: {consecutive_failures} consecutive failures, "
                        f"triggering reconnection"
                    )
                    self._handle_disconnect()
                    break  # Exit health check, will restart after reconnection

            self.logger.debug("Health check thread exiting")

        self._health_check_timer = threading.Thread(
            target=check_health,
            name='IBKRHealthCheck',
            daemon=True
        )
        self._health_check_timer.start()

    async def _async_heartbeat(self) -> Optional[str]:
        """
        Active heartbeat - request server time to verify connection is truly alive.
        Returns server time string if successful, None if failed.

        IMPORTANT: Must use async version (reqCurrentTimeAsync) because this
        coroutine runs on the IB event loop. The sync reqCurrentTime() tries
        to call self._run() which re-enters the already-running event loop,
        causing a deadlock and guaranteed failure.
        """
        try:
            server_time = await self._ib.reqCurrentTimeAsync()
            if server_time:
                return server_time.isoformat() if hasattr(server_time, 'isoformat') else str(server_time)
            return None
        except Exception as e:
            self.logger.debug(f"Heartbeat request failed: {e}")
            return None
    
    def _stop_health_check(self):
        """Stop health check timer."""
        # Timer thread will stop on its own when shutdown is set
        pass
    
    # =========================================================================
    # Thread-safe query methods
    # =========================================================================
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current quote for a symbol (thread-safe).
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            
        Returns:
            Dict with price data or None if unavailable
        """
        if not self.is_connected():
            self.logger.warning("Not connected to IBKR")
            return None
        
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_get_quote(symbol),
                self._loop
            )
            return future.result(timeout=10.0)
        except Exception as e:
            self.logger.debug(f"Quote error for {symbol}: {e}")
            return None
    
    async def _async_get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Async quote retrieval."""
        from ib_insync import Stock
        
        contract = Stock(symbol, 'SMART', 'USD')
        
        try:
            # Qualify contract
            await self._ib.qualifyContractsAsync(contract)
            
            if not contract.conId:
                return None
            
            # Request market data snapshot
            # NOTE: Generic tick types (like '233') are NOT compatible with snapshot mode
            ticker = self._ib.reqMktData(contract, '', True, False)
            
            # Wait for data - increased time for reliable results
            await asyncio.sleep(2.0)
            
            def safe_float(val, default=0.0):
                if val is None or (isinstance(val, float) and val != val):
                    return default
                return float(val)
            
            # Check if volume data is available (not None and not NaN)
            volume_available = ticker.volume is not None and not (isinstance(ticker.volume, float) and ticker.volume != ticker.volume)
            
            last_price = safe_float(ticker.last) or safe_float(ticker.close)
            if last_price <= 0:
                bid = safe_float(ticker.bid)
                ask = safe_float(ticker.ask)
                if bid > 0 and ask > 0:
                    last_price = (bid + ask) / 2
            
            # Cancel market data subscription
            self._ib.cancelMktData(contract)
            
            if last_price <= 0:
                return None
            
            return {
                'symbol': symbol,
                'last': last_price,
                'bid': safe_float(ticker.bid),
                'ask': safe_float(ticker.ask),
                'volume': int(safe_float(ticker.volume)),
                'avg_volume': int(safe_float(ticker.avVolume, 500000)),
                'high': safe_float(ticker.high),
                'low': safe_float(ticker.low),
                'open': safe_float(ticker.open),
                'close': safe_float(ticker.close),
                'volume_available': volume_available,
            }
            
        except Exception as e:
            self.logger.debug(f"Quote fetch error for {symbol}: {e}")
            return None
    
    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get quotes for multiple symbols (thread-safe).
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dict mapping symbols to their quote data
        """
        results = {}
        for symbol in symbols:
            quote = self.get_quote(symbol)
            if quote:
                results[symbol] = quote
        return results
    
    def sleep(self, seconds: float):
        """
        Process IB events for specified duration.
        Must be called from the IB thread.
        """
        if self._ib:
            self._ib.sleep(seconds)
    
    def qualifyContracts(self, *contracts):
        """Qualify contracts (thread-safe wrapper)."""
        if not self.is_connected():
            return []
        
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ib.qualifyContractsAsync(*contracts),
                self._loop
            )
            return future.result(timeout=10.0)
        except Exception as e:
            self.logger.debug(f"Contract qualification error: {e}")
            return []
    
    def reqMktData(self, contract, genericTickList='', snapshot=True, regulatorySnapshot=False):
        """Request market data (must be called carefully - prefer get_quote)."""
        if not self.is_connected():
            return None
        return self._ib.reqMktData(contract, genericTickList, snapshot, regulatorySnapshot)
    
    # =========================================================================
    # Status and diagnostics
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current connection status."""
        return {
            'connected': self.is_connected(),
            'host': self.host,
            'port': self.port,
            'client_id': self.client_id,
            'last_connect_time': self._last_connect_time.isoformat() if self._last_connect_time else None,
            'last_disconnect_time': self._last_disconnect_time.isoformat() if self._last_disconnect_time else None,
            'reconnect_attempts': self._reconnect_attempts,
            'reconnecting': self._reconnecting,
            'reconnect_enabled': self.reconnect_config.enabled,
        }
