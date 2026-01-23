"""
CANSLIM Monitor - Service Integration Test Harness
Phase 2: Full service testing with mock data

Runs the complete service stack with simulated data to verify:
- Thread lifecycle (start, run, stop)
- Data flow through all components
- Database persistence
- Discord delivery (dry-run)
- IPC command handling
- Graceful shutdown

Usage:
    python -m service.test_harness
    python -m service.test_harness --duration 60 --discord-test
"""

import logging
import threading
import time
import queue
import tempfile
import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import random
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data import DatabaseManager, init_database
from canslim_monitor.data.models import Position, Alert, MarketRegime
from canslim_monitor.data.repositories import RepositoryManager
from canslim_monitor.service.threads import ThreadManager, BaseThread
from canslim_monitor.service.threads.breakout_thread import BreakoutThread
from canslim_monitor.service.threads.position_thread import PositionThread
from canslim_monitor.service.threads.market_thread import MarketThread
from canslim_monitor.integrations.discord_notifier import DiscordNotifier


# =============================================================================
# Mock Data Providers
# =============================================================================

class MockIBKRClient:
    """
    Mock IBKR client that simulates real-time market data.
    
    Provides controlled test scenarios:
    - Normal trading
    - Breakout events
    - Stop loss triggers
    - Market regime changes
    """
    
    def __init__(self, scenario: str = 'normal'):
        self.scenario = scenario
        self.connected = False
        self.subscriptions: Dict[str, Any] = {}
        self._tick_count = 0
        self._base_prices: Dict[str, float] = {}
        self.logger = logging.getLogger('mock.ibkr')
        
        # Scenario configurations
        self._scenarios = {
            'normal': {'volatility': 0.002, 'trend': 0.0},
            'breakout': {'volatility': 0.005, 'trend': 0.02},
            'selloff': {'volatility': 0.008, 'trend': -0.03},
            'choppy': {'volatility': 0.01, 'trend': 0.0},
        }
    
    def connect(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1) -> bool:
        """Simulate connection."""
        self.logger.info(f"MockIBKR connecting to {host}:{port} (client_id={client_id})")
        time.sleep(0.1)  # Simulate connection delay
        self.connected = True
        self.logger.info("MockIBKR connected successfully")
        return True
    
    def disconnect(self):
        """Simulate disconnection."""
        self.connected = False
        self.subscriptions.clear()
        self.logger.info("MockIBKR disconnected")
    
    def is_connected(self) -> bool:
        return self.connected
    
    def subscribe_realtime(self, symbol: str, callback=None) -> bool:
        """Subscribe to real-time data for a symbol."""
        if not self.connected:
            return False
        
        # Initialize base price if not set
        if symbol not in self._base_prices:
            self._base_prices[symbol] = self._get_initial_price(symbol)
        
        self.subscriptions[symbol] = {
            'callback': callback,
            'subscribed_at': datetime.now()
        }
        self.logger.debug(f"Subscribed to {symbol}")
        return True
    
    def unsubscribe(self, symbol: str):
        """Unsubscribe from symbol."""
        self.subscriptions.pop(symbol, None)
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current quote for symbol."""
        if not self.connected:
            return None
        
        self._tick_count += 1
        
        # Get or initialize base price
        if symbol not in self._base_prices:
            self._base_prices[symbol] = self._get_initial_price(symbol)
        
        base = self._base_prices[symbol]
        scenario_config = self._scenarios.get(self.scenario, self._scenarios['normal'])
        
        # Calculate price movement
        volatility = scenario_config['volatility']
        trend = scenario_config['trend']
        
        # Add some randomness
        change = random.gauss(trend, volatility)
        price = base * (1 + change)
        
        # Update base price for next tick (random walk)
        self._base_prices[symbol] = price
        
        # Generate volume
        avg_volume = self._get_avg_volume(symbol)
        volume_ratio = random.uniform(0.8, 1.5)
        if self.scenario == 'breakout':
            volume_ratio = random.uniform(1.5, 2.5)  # High volume on breakout
        
        return {
            'symbol': symbol,
            'last': round(price, 2),
            'bid': round(price * 0.9999, 2),
            'ask': round(price * 1.0001, 2),
            'volume': int(avg_volume * volume_ratio),
            'avg_volume': avg_volume,
            'volume_ratio': volume_ratio,
            'change_pct': change * 100,
            'timestamp': datetime.now()
        }
    
    def get_index_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get index quote (SPY, QQQ, DIA)."""
        quote = self.get_quote(symbol)
        if quote:
            # Add MA data for indices
            quote['ma50'] = quote['last'] * 0.98
            quote['ma200'] = quote['last'] * 0.92
            quote['prev_close'] = quote['last'] / (1 + quote['change_pct']/100)
        return quote
    
    def _get_initial_price(self, symbol: str) -> float:
        """Get initial price for a symbol."""
        # Common symbols
        prices = {
            'SPY': 590.0, 'QQQ': 510.0, 'DIA': 430.0,
            'AAPL': 185.0, 'MSFT': 410.0, 'NVDA': 480.0,
            'GOOGL': 175.0, 'AMZN': 185.0, 'META': 560.0,
            'TSLA': 250.0, 'AMD': 145.0, 'AVGO': 170.0,
        }
        return prices.get(symbol, random.uniform(50, 200))
    
    def _get_avg_volume(self, symbol: str) -> int:
        """Get average volume for a symbol."""
        volumes = {
            'SPY': 80_000_000, 'QQQ': 50_000_000, 'DIA': 5_000_000,
            'AAPL': 60_000_000, 'MSFT': 25_000_000, 'NVDA': 45_000_000,
        }
        return volumes.get(symbol, random.randint(1_000_000, 10_000_000))
    
    def set_scenario(self, scenario: str):
        """Change the market scenario."""
        if scenario in self._scenarios:
            self.scenario = scenario
            self.logger.info(f"Scenario changed to: {scenario}")


class MockDiscordNotifier:
    """
    Mock Discord notifier that captures alerts for verification.
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.alerts_sent: List[Dict[str, Any]] = []
        self.logger = logging.getLogger('mock.discord')
    
    def send(self, content: str = None, embed: dict = None, channel: str = 'default', **kwargs) -> bool:
        """Capture alert - accepts any kwargs for flexibility."""
        # Handle both 'content' and 'message' parameter names
        message = content or kwargs.get('message', '')
        
        alert = {
            'timestamp': datetime.now(),
            'channel': channel,
            'content': message,
            'embed': embed,
            'extra': kwargs
        }
        self.alerts_sent.append(alert)
        preview = message[:50] if message else (str(embed)[:50] if embed else 'empty')
        self.logger.info(f"[MOCK DISCORD] Channel: {channel}, Content: {preview}...")
        return True
    
    def send_breakout_alert(self, **kwargs) -> bool:
        """Capture breakout alert."""
        self.alerts_sent.append({'type': 'breakout', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[BREAKOUT ALERT] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_pivot_cross_alert(self, **kwargs) -> bool:
        """Capture pivot cross alert (alias for breakout)."""
        self.alerts_sent.append({'type': 'breakout', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[PIVOT CROSS] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_stop_loss_alert(self, **kwargs) -> bool:
        """Capture stop loss alert."""
        self.alerts_sent.append({'type': 'stop_loss', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[STOP LOSS ALERT] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_profit_target_alert(self, **kwargs) -> bool:
        """Capture profit target alert."""
        self.alerts_sent.append({'type': 'profit_target', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[PROFIT TARGET] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_pyramid_alert(self, **kwargs) -> bool:
        """Capture pyramid alert."""
        self.alerts_sent.append({'type': 'pyramid', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[PYRAMID] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_health_alert(self, **kwargs) -> bool:
        """Capture health alert."""
        self.alerts_sent.append({'type': 'health', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[HEALTH ALERT] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def send_market_regime_alert(self, **kwargs) -> bool:
        """Capture market regime alert."""
        self.alerts_sent.append({'type': 'market_regime', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[MARKET REGIME ALERT] {kwargs.get('regime', 'N/A')}")
        return True
    
    def send_distribution_day_alert(self, **kwargs) -> bool:
        """Capture distribution day alert."""
        self.alerts_sent.append({'type': 'distribution_day', 'data': kwargs, 'timestamp': datetime.now()})
        self.logger.info(f"[DISTRIBUTION DAY ALERT] {kwargs.get('symbol', 'N/A')}")
        return True
    
    def get_alert_count(self, alert_type: str = None) -> int:
        """Get count of alerts by type."""
        if alert_type:
            return len([a for a in self.alerts_sent if a.get('type') == alert_type])
        return len(self.alerts_sent)
    
    def clear_alerts(self):
        """Clear captured alerts."""
        self.alerts_sent.clear()


# =============================================================================
# Test Harness
# =============================================================================

class ServiceTestHarness:
    """
    Integration test harness for the CANSLIM Monitor service.
    
    Runs all components together with mock or live data and verifies:
    - Threads start and run correctly
    - Data flows through the system
    - Database persistence works
    - Alerts are generated appropriately
    - Shutdown is graceful
    """
    
    def __init__(
        self,
        duration: int = 30,
        scenario: str = 'normal',
        discord_test: bool = False,
        discord_webhook: str = None,
        live_ibkr: bool = False,
        ibkr_port: int = 7497,
        ibkr_client_id: int = 20
    ):
        """
        Initialize test harness.
        
        Args:
            duration: Test duration in seconds
            scenario: Market scenario (normal, breakout, selloff, choppy) - only for mock mode
            discord_test: If True, send to real Discord (test channel)
            discord_webhook: Webhook URL for Discord test
            live_ibkr: If True, connect to real IBKR TWS/Gateway
            ibkr_port: IBKR port (7497=paper, 7496=live, 4001/4002=gateway)
            ibkr_client_id: IBKR client ID
        """
        self.duration = duration
        self.scenario = scenario
        self.discord_test = discord_test
        self.discord_webhook = discord_webhook
        self.live_ibkr = live_ibkr
        self.ibkr_port = ibkr_port
        self.ibkr_client_id = ibkr_client_id
        
        # Set up logging
        self.logger = logging.getLogger('test_harness')
        
        # Components
        self.db: Optional[DatabaseManager] = None
        self.ibkr: Any = None  # MockIBKRClient or IBKRClient
        self.discord: Any = None  # MockDiscordNotifier or DiscordNotifier
        self.thread_manager: Optional[ThreadManager] = None
        
        # Test state
        self.db_path: Optional[str] = None
        self.results: Dict[str, Any] = {}
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
    
    def setup(self):
        """Set up test environment."""
        self.logger.info("=" * 60)
        self.logger.info("CANSLIM Monitor - Service Integration Test")
        self.logger.info("=" * 60)
        mode = "LIVE IBKR" if self.live_ibkr else f"Mock ({self.scenario})"
        self.logger.info(f"Duration: {self.duration}s | Mode: {mode}")
        self.logger.info("=" * 60)
        
        # Create temp database
        self.db_path = tempfile.mktemp(suffix='.db')
        self.logger.info(f"Database: {self.db_path}")
        
        # Initialize database
        self.db = init_database(self.db_path)
        self.logger.info("Database initialized")
        
        # Seed test data
        self._seed_test_data()
        
        # Create IBKR client (real or mock)
        if self.live_ibkr:
            self._setup_live_ibkr()
        else:
            self.ibkr = MockIBKRClient(scenario=self.scenario)
            self.ibkr.connect()
            self.logger.info("Mock IBKR connected")
        
        # Create Discord notifier (mock or real)
        if self.discord_test and self.discord_webhook:
            self.discord = DiscordNotifier(
                webhooks={
                    'default': self.discord_webhook,
                    'breakout-alerts': self.discord_webhook,
                    'position-alerts': self.discord_webhook,
                    'market-alerts': self.discord_webhook
                },
                default_webhook=self.discord_webhook,
                enabled=True
            )
            self.logger.info("Real Discord notifier created (TEST MODE)")
        else:
            self.discord = MockDiscordNotifier(dry_run=True)
            self.logger.info("Mock Discord notifier created")
        
        # Create thread manager
        self.thread_manager = ThreadManager(logger=self.logger)
        self.logger.info("Thread manager created")
        
        # Create worker threads
        self._create_threads()
        
        self.logger.info("Setup complete")
        self.logger.info("-" * 60)
    
    def _setup_live_ibkr(self):
        """Set up live IBKR connection."""
        from integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
        
        self.logger.info(f"Connecting to IBKR TWS/Gateway on port {self.ibkr_port}...")
        self.logger.info(f"  Client ID: {self.ibkr_client_id}")
        
        self.ibkr = ThreadSafeIBKRClient(
            host='127.0.0.1',
            port=self.ibkr_port,
            client_id=self.ibkr_client_id
        )
        
        if not self.ibkr.connect(timeout=15.0):
            raise ConnectionError(
                f"Failed to connect to IBKR on port {self.ibkr_port}. "
                f"Make sure TWS/Gateway is running and accepting connections."
            )
        
        self.logger.info("✅ Live IBKR connected successfully")
        
        # Test with a quick quote
        test_quote = self.ibkr.get_quote('SPY')
        if test_quote:
            self.logger.info(f"  SPY test quote: ${test_quote.get('last', 'N/A')}")
        else:
            self.logger.warning("  Could not fetch SPY test quote")
        
        # Create Discord notifier (mock or real)
        if self.discord_test and self.discord_webhook:
            self.discord = DiscordNotifier(
                webhooks={
                    'default': self.discord_webhook,
                    'breakout-alerts': self.discord_webhook,
                    'position-alerts': self.discord_webhook,
                    'market-alerts': self.discord_webhook
                },
                default_webhook=self.discord_webhook,
                enabled=True
            )
            self.logger.info("Real Discord notifier created (TEST MODE)")
        else:
            self.discord = MockDiscordNotifier(dry_run=True)
            self.logger.info("Mock Discord notifier created")
        
        # Create thread manager
        self.thread_manager = ThreadManager(logger=self.logger)
        self.logger.info("Thread manager created")
        
        # Create worker threads
        self._create_threads()
        
        self.logger.info("Setup complete")
        self.logger.info("-" * 60)
    
    def _seed_test_data(self):
        """Seed database with test positions."""
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            
            # Create watchlist positions (State 0)
            # Updated pivot prices for January 2026
            watchlist = [
                {'symbol': 'NVDA', 'pivot': 128.0, 'stop': 121.0, 'pattern': 'Cup w/Handle'},
                {'symbol': 'AAPL', 'pivot': 255.0, 'stop': 245.0, 'pattern': 'Flat Base'},
                {'symbol': 'MSFT', 'pivot': 460.0, 'stop': 445.0, 'pattern': 'Double Bottom'},
                {'symbol': 'AMD', 'pivot': 115.0, 'stop': 108.0, 'pattern': 'Cup w/Handle'},
                {'symbol': 'GOOGL', 'pivot': 330.0, 'stop': 315.0, 'pattern': 'Ascending Base'},
            ]
            
            for w in watchlist:
                repos.positions.create(
                    symbol=w['symbol'],
                    state=0,  # Watching
                    pivot=w['pivot'],
                    stop_price=w['stop'],
                    pattern=w['pattern'],
                    base_stage='2',
                    entry_score=75,
                    entry_grade='B+',
                    portfolio='Test',
                    watch_date=date.today()
                )
            
            # Create active positions (State 1)
            active = [
                {'symbol': 'META', 'entry': 600.0, 'stop': 570.0, 'shares': 50},
                {'symbol': 'AVGO', 'entry': 340.0, 'stop': 320.0, 'shares': 100},
            ]
            
            for a in active:
                repos.positions.create(
                    symbol=a['symbol'],
                    state=1,  # Active
                    e1_price=a['entry'],
                    e1_shares=a['shares'],
                    e1_date=date.today() - timedelta(days=5),
                    entry_date=date.today() - timedelta(days=5),
                    stop_price=a['stop'],
                    total_shares=a['shares'],
                    avg_cost=a['entry'],
                    pattern='Breakout',
                    base_stage='2',
                    entry_score=80,
                    entry_grade='A',
                    portfolio='Test'
                )
            
            # Create market regime
            repos.market_regime.create_daily_regime(
                regime_date=date.today(),
                regime='BULLISH',
                regime_score=65,
                distribution_days={'spy': 2, 'qqq': 3, 'total': 5},
                ftd_data={'active': True, 'date': date.today() - timedelta(days=15), 'days_since': 15},
                recommended_exposure=4
            )
            
            session.commit()
            self.logger.info(f"Seeded {len(watchlist)} watchlist + {len(active)} active positions")
            
        finally:
            session.close()
    
    def _create_threads(self):
        """Create and register worker threads."""
        shutdown = self.thread_manager.shutdown_event
        
        # Breakout thread - monitors watchlist
        breakout = BreakoutThread(
            shutdown_event=shutdown,
            db=self.db,
            ibkr_client=self.ibkr,
            discord_notifier=self.discord,
            poll_interval=2,  # Fast for testing
            market_hours_only=False  # Run anytime for testing
        )
        self.thread_manager.register(breakout)
        
        # Position thread - monitors active positions
        position = PositionThread(
            shutdown_event=shutdown,
            db=self.db,
            ibkr_client=self.ibkr,
            discord_notifier=self.discord,
            poll_interval=2,
            market_hours_only=False
        )
        self.thread_manager.register(position)
        
        # Market thread - monitors indices
        market = MarketThread(
            shutdown_event=shutdown,
            db=self.db,
            ibkr_client=self.ibkr,
            discord_notifier=self.discord,
            poll_interval=5,
            market_hours_only=False
        )
        self.thread_manager.register(market)
        
        self.logger.info(f"Created {len(self.thread_manager.threads)} worker threads")
    
    def run(self):
        """Run the integration test."""
        self._start_time = datetime.now()
        
        self.logger.info("Starting worker threads...")
        self.thread_manager.start_all()
        
        # Monitor progress
        try:
            self._monitor_test()
        except KeyboardInterrupt:
            self.logger.warning("Test interrupted by user")
        
        self._end_time = datetime.now()
        
        # Shutdown
        self.logger.info("Stopping worker threads...")
        self.thread_manager.stop_all(timeout=5)
        
        # Collect results
        self._collect_results()
    
    def _monitor_test(self):
        """Monitor test progress and log status."""
        elapsed = 0
        check_interval = 5
        
        while elapsed < self.duration:
            time.sleep(check_interval)
            elapsed += check_interval
            
            # Get thread status
            status = self.thread_manager.get_status()
            
            # Log progress
            self.logger.info(f"[{elapsed}s/{self.duration}s] Thread Status:")
            for name, info in status.items():
                self.logger.info(f"  {name}: runs={info.get('run_count', 0)}, errors={info.get('error_count', 0)}")
            
            # Log mock Discord alerts
            if isinstance(self.discord, MockDiscordNotifier):
                alert_count = self.discord.get_alert_count()
                self.logger.info(f"  Discord alerts captured: {alert_count}")
            
            # Change scenario mid-test for variety (mock mode only)
            if not self.live_ibkr and elapsed == self.duration // 2 and self.scenario == 'normal':
                self.logger.info(">>> Switching to BREAKOUT scenario mid-test <<<")
                self.ibkr.set_scenario('breakout')
    
    def _collect_results(self):
        """Collect test results."""
        duration = (self._end_time - self._start_time).total_seconds()
        
        # Thread statistics
        thread_stats = self.thread_manager.get_status()
        
        # Database statistics
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            alert_count = session.query(Alert).count()
            position_count = session.query(Position).count()
        finally:
            session.close()
        
        # Discord statistics
        discord_stats = {}
        if isinstance(self.discord, MockDiscordNotifier):
            discord_stats = {
                'total_alerts': self.discord.get_alert_count(),
                'breakout_alerts': self.discord.get_alert_count('breakout'),
                'stop_loss_alerts': self.discord.get_alert_count('stop_loss'),
                'market_regime_alerts': self.discord.get_alert_count('market_regime'),
            }
        
        self.results = {
            'duration_seconds': duration,
            'mode': 'LIVE IBKR' if self.live_ibkr else f'Mock ({self.scenario})',
            'live_ibkr': self.live_ibkr,
            'threads': thread_stats,
            'database': {
                'alerts_created': alert_count,
                'positions_total': position_count
            },
            'discord': discord_stats
        }
    
    def report(self):
        """Print test report."""
        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info("TEST RESULTS")
        self.logger.info("=" * 60)
        
        # Summary
        print(f"\n{'='*60}")
        print("CANSLIM Monitor - Service Integration Test Results")
        print(f"{'='*60}\n")
        
        print(f"Duration: {self.results['duration_seconds']:.1f} seconds")
        print(f"Mode: {self.results['mode']}")
        
        # Thread results
        print(f"\n{'─'*40}")
        print("THREAD PERFORMANCE")
        print(f"{'─'*40}")
        
        total_runs = 0
        total_errors = 0
        all_healthy = True
        
        for name, stats in self.results['threads'].items():
            runs = stats.get('run_count', 0)
            errors = stats.get('error_count', 0)
            status = stats.get('status', 'unknown')
            
            total_runs += runs
            total_errors += errors
            
            health = "✅" if errors == 0 and runs > 0 else "❌"
            if errors > 0 or runs == 0:
                all_healthy = False
            
            print(f"  {health} {name}: {runs} cycles, {errors} errors, status={status}")
        
        # Database results
        print(f"\n{'─'*40}")
        print("DATABASE ACTIVITY")
        print(f"{'─'*40}")
        print(f"  Alerts created: {self.results['database']['alerts_created']}")
        print(f"  Positions tracked: {self.results['database']['positions_total']}")
        
        # Discord results
        if self.results['discord']:
            print(f"\n{'─'*40}")
            print("DISCORD ALERTS (Mock)")
            print(f"{'─'*40}")
            for key, value in self.results['discord'].items():
                print(f"  {key}: {value}")
        
        # Overall verdict
        print(f"\n{'='*60}")
        if all_healthy and total_runs > 0:
            print("✅ INTEGRATION TEST PASSED")
        else:
            print("❌ INTEGRATION TEST FAILED")
            if total_errors > 0:
                print(f"   - {total_errors} errors occurred")
            if total_runs == 0:
                print(f"   - No work cycles completed")
        print(f"{'='*60}\n")
        
        return all_healthy
    
    def cleanup(self):
        """Clean up test resources."""
        if self.ibkr:
            self.ibkr.disconnect()
        
        # Close database connection before deleting
        if self.db:
            try:
                self.db.close()
            except Exception as e:
                self.logger.warning(f"Error closing database: {e}")
        
        # Small delay to ensure file handles are released (Windows)
        time.sleep(0.5)
        
        if self.db_path and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
                self.logger.info(f"Removed temp database: {self.db_path}")
            except PermissionError:
                self.logger.warning(f"Could not remove temp database (in use): {self.db_path}")
            except Exception as e:
                self.logger.warning(f"Error removing temp database: {e}")


# =============================================================================
# IPC Test
# =============================================================================

class IPCTestHarness:
    """Test IPC communication between service and GUI."""
    
    def __init__(self):
        self.logger = logging.getLogger('test_harness.ipc')
        self.results = {}
    
    def run(self):
        """Run IPC tests."""
        from service.ipc import create_pipe_server, create_pipe_client
        
        self.logger.info("Testing IPC communication...")
        
        # Create server
        command_queue = queue.Queue()
        response_queue = queue.Queue()
        shutdown_event = threading.Event()
        
        server = create_pipe_server(
            command_queue=command_queue,
            response_queue=response_queue,
            shutdown_event=shutdown_event
        )
        
        # Start server in background
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        time.sleep(0.5)  # Let server start
        
        # Create client and test commands
        client = create_pipe_client()
        
        tests_passed = 0
        tests_failed = 0
        
        # Test 1: Ping
        try:
            # Put expected response in queue
            response_queue.put({'status': 'ok', 'message': 'pong'})
            
            result = client.send_command('PING')
            if result and result.get('status') == 'ok':
                self.logger.info("✅ PING test passed")
                tests_passed += 1
            else:
                self.logger.error("❌ PING test failed")
                tests_failed += 1
        except Exception as e:
            self.logger.error(f"❌ PING test error: {e}")
            tests_failed += 1
        
        # Test 2: Get Status
        try:
            response_queue.put({
                'status': 'ok',
                'data': {'threads': {}, 'uptime': 100}
            })
            
            result = client.send_command('GET_STATUS')
            if result and result.get('status') == 'ok':
                self.logger.info("✅ GET_STATUS test passed")
                tests_passed += 1
            else:
                self.logger.error("❌ GET_STATUS test failed")
                tests_failed += 1
        except Exception as e:
            self.logger.error(f"❌ GET_STATUS test error: {e}")
            tests_failed += 1
        
        # Cleanup
        shutdown_event.set()
        client.close()
        
        self.results = {
            'tests_passed': tests_passed,
            'tests_failed': tests_failed
        }
        
        return tests_failed == 0


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point for test harness."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='CANSLIM Monitor - Service Integration Test'
    )
    parser.add_argument(
        '--duration', type=int, default=30,
        help='Test duration in seconds (default: 30)'
    )
    parser.add_argument(
        '--scenario', choices=['normal', 'breakout', 'selloff', 'choppy'],
        default='normal', help='Market scenario for mock data (default: normal)'
    )
    parser.add_argument(
        '--discord-test', action='store_true',
        help='Send alerts to real Discord test channel'
    )
    parser.add_argument(
        '--discord-webhook', type=str,
        help='Discord webhook URL for testing'
    )
    parser.add_argument(
        '--live-ibkr', action='store_true',
        help='Use live IBKR connection instead of mock data'
    )
    parser.add_argument(
        '--ibkr-port', type=int, default=7497,
        help='IBKR TWS/Gateway port (7497=paper, 7496=live, 4001/4002=gateway)'
    )
    parser.add_argument(
        '--ibkr-client-id', type=int, default=20,
        help='IBKR client ID (default: 20)'
    )
    parser.add_argument(
        '--ipc-only', action='store_true',
        help='Only run IPC tests'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Verbose logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Run IPC tests only
    if args.ipc_only:
        harness = IPCTestHarness()
        success = harness.run()
        print(f"\nIPC Tests: {'PASSED' if success else 'FAILED'}")
        return 0 if success else 1
    
    # Run full integration test
    harness = ServiceTestHarness(
        duration=args.duration,
        scenario=args.scenario,
        discord_test=args.discord_test,
        discord_webhook=args.discord_webhook,
        live_ibkr=args.live_ibkr,
        ibkr_port=args.ibkr_port,
        ibkr_client_id=args.ibkr_client_id
    )
    
    try:
        harness.setup()
        harness.run()
        success = harness.report()
    finally:
        harness.cleanup()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
