"""
CANSLIM Monitor - Service Controller
Main controller managing threads, IPC, and shared resources.

FIXED: Added asyncio event loop handling for Windows Service compatibility
UPDATED: Replaced MarketThread with RegimeThread (ported from MarketRegime-MonitorSystem)
"""

import asyncio
import logging
import os
import queue
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional

from .threads import BreakoutThread, PositionThread, MarketThread, MaintenanceThread
from .ipc import create_pipe_server

# Phase 2 dependencies
from ..utils.scoring_engine import ScoringEngine
from ..utils.position_sizer import PositionSizer
from ..services.alert_service import AlertService


def _ensure_event_loop():
    """
    Ensure there's an asyncio event loop for the current thread.
    
    CRITICAL: ib_insync requires an event loop to exist before import.
    Windows Services run in background threads without event loops by default.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


class ServiceController:
    """
    Central controller for the CANSLIM Monitor service.
    
    Responsibilities:
    - Initialize shared resources (DB, IBKR, Discord)
    - Spawn and manage worker threads
    - Handle IPC commands from GUI
    - Graceful shutdown coordination
    """
    
    def __init__(
        self,
        config_path: str = None,
        db_path: str = None,
        logger: Optional[logging.Logger] = None
    ):
        self.config_path = config_path
        self.db_path = db_path
        self.logger = logger or logging.getLogger('canslim.controller')
        
        # Shared state
        self.shutdown_event = threading.Event()
        self.command_queue = queue.Queue()
        
        # Components (initialized in start())
        self.threads: Dict[str, Any] = {}
        self.pipe_server = None
        self.ibkr_client = None
        self.discord_notifier = None
        self.db_session_factory = None
        self.config = {}
        self.market_calendar = None
        
        # Phase 2 components
        self.scoring_engine = None
        self.position_sizer = None
        self.alert_service = None

        # Market data — provider abstraction layer
        self.provider_factory = None
        self.historical_provider = None
        self.realtime_provider = None
        self.futures_provider = None
        self.polygon_client = None  # Legacy compat — backed by historical_provider.client

        # Tracking
        self._start_time: Optional[datetime] = None
        self._is_running = False
    
    def start(self):
        """Start the service controller and all threads."""
        self.logger.info("Starting CANSLIM Monitor Service Controller")
        
        # CRITICAL: Ensure event loop exists BEFORE importing ib_insync
        # Windows Services run in background threads without event loops
        _ensure_event_loop()
        self.logger.debug("Event loop initialized for service thread")
        
        self._start_time = datetime.now()
        self._is_running = True
        
        # Load configuration
        self._load_config()
        
        # Initialize shared resources
        self._init_market_calendar()
        self._init_database()
        self._init_ibkr()
        self._init_discord()
        self._init_providers()

        # Initialize Phase 2 components
        self._init_scoring_engine()
        self._init_position_sizer()
        self._init_alert_service()
        
        # Create worker threads
        self._create_threads()
        
        # Start IPC server
        self._start_ipc_server()
        
        # Start worker threads
        for name, thread in self.threads.items():
            thread.start()
            self.logger.info(f"{name} thread starting (poll: {thread.poll_interval}s)")
        
        self.logger.info("Service controller started successfully")
        
        # Main command loop
        self._command_loop()
    
    def shutdown(self):
        """Gracefully shutdown all components."""
        self.logger.info("Shutting down service controller...")
        
        self._is_running = False
        self.shutdown_event.set()
        
        # Wait for threads to finish
        for name, thread in self.threads.items():
            if thread.is_alive():
                self.logger.debug(f"Waiting for {name} thread...")
                thread.join(timeout=5)
                if thread.is_alive():
                    self.logger.warning(f"{name} thread did not stop gracefully")
        
        # Stop IPC server
        if self.pipe_server and self.pipe_server.is_alive():
            self.pipe_server.join(timeout=2)
        
        # Cleanup resources
        self._cleanup()
        
        self.logger.info("Service controller stopped")
    
    def _load_config(self):
        """Load configuration from file."""
        if not self.config_path:
            self.logger.warning("No config path specified, using defaults")
            self.config = {}
            return
        
        try:
            import yaml
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
            self.logger.info(f"Loaded config from: {self.config_path}")
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            self.config = {}
    
    def _init_market_calendar(self):
        """Initialize shared MarketCalendar with Polygon API key."""
        try:
            from ..utils.market_calendar import init_market_calendar
            api_key = self.config.get('polygon', {}).get('api_key', '')
            self.market_calendar = init_market_calendar(api_key=api_key)
            self.logger.info(
                "MarketCalendar initialized (api_key=%s)",
                'set' if api_key else 'none — using fallback calendar'
            )
        except Exception as e:
            self.logger.warning(f"MarketCalendar init failed: {e}")

    def _init_database(self):
        """Initialize database connection."""
        if not self.db_path:
            self.logger.warning("No database path specified")
            return
        
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_engine(f'sqlite:///{self.db_path}')
            self.db_session_factory = sessionmaker(bind=engine)
            self.logger.info(f"Database initialized: {self.db_path}")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
    
    def _init_ibkr(self):
        """Initialize IBKR connection using thread-safe IBKRClient wrapper."""
        ibkr_config = self.config.get('ibkr', {})
        if not ibkr_config:
            self.logger.warning("No IBKR config found")
            return
        
        try:
            # Ensure event loop exists before importing ib_insync
            _ensure_event_loop()
            
            # Use ThreadSafeIBKRClient which manages its own event loop in a dedicated thread
            from ..integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
            
            host = ibkr_config.get('host', '127.0.0.1')
            port = ibkr_config.get('port', 4001)
            client_id_base = ibkr_config.get('client_id_base', 20)
            timeout = ibkr_config.get('timeout', 30)
            max_retries = ibkr_config.get('max_client_id_retries', 5)
            
            self.logger.info(f"IBKR config: host={host}, port={port}, client_id_base={client_id_base}")
            
            # Load reconnect config from user config
            from ..integrations.ibkr_client_threadsafe import ReconnectConfig
            reconnect_settings = ibkr_config.get('reconnect', {})
            reconnect_config = ReconnectConfig(
                enabled=reconnect_settings.get('enabled', True),
                initial_delay=reconnect_settings.get('initial_delay', 30.0),
                max_delay=reconnect_settings.get('max_delay', 300.0),
                backoff_factor=reconnect_settings.get('backoff_factor', 1.5),
                max_attempts=reconnect_settings.get('max_attempts', 0),  # 0 = unlimited
                health_check_interval=reconnect_settings.get('health_check_interval', 30.0),
                gateway_restart_delay=reconnect_settings.get('gateway_restart_delay', 120.0),
            )

            self.logger.info(
                f"IBKR reconnect config: initial_delay={reconnect_config.initial_delay}s, "
                f"gateway_restart_delay={reconnect_config.gateway_restart_delay}s"
            )

            # Try connecting with incrementing client IDs to avoid conflicts
            for attempt in range(max_retries):
                client_id = client_id_base + attempt
                try:
                    self.logger.info(f"Connecting to IBKR at {host}:{port} (client_id={client_id})")

                    # ThreadSafeIBKRClient runs IB in its own thread with event loop
                    self.ibkr_client = ThreadSafeIBKRClient(
                        host=host,
                        port=port,
                        client_id=client_id,
                        reconnect_config=reconnect_config,
                    )
                    
                    if self.ibkr_client.connect():
                        self.logger.info(f"IBKR connected successfully (client_id={client_id})")
                        return
                    else:
                        self.logger.warning(f"IBKR connection failed (client_id={client_id})")
                        self.ibkr_client = None
                        
                except Exception as e:
                    self.logger.warning(f"IBKR connection attempt {attempt+1} failed: {e}")
                    self.ibkr_client = None
            
            self.logger.error(f"Failed to connect to IBKR after {max_retries} attempts")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize IBKR: {e}")
            self.ibkr_client = None
    
    def _init_discord(self):
        """Initialize Discord notifier."""
        from ..utils.logging import get_logger
        
        discord_config = self.config.get('discord', {})
        
        if not discord_config:
            self.logger.warning("No Discord config found - Discord alerts will be disabled")
            return
        
        try:
            from ..integrations.discord_notifier import DiscordNotifier
            
            # Get webhooks from nested 'webhooks' dict (preferred)
            # Config format:
            #   discord:
            #     webhooks:
            #       breakout: "https://..."
            #       position: "https://..."
            #       market: "https://..."
            #       system: "https://..."
            webhooks_config = discord_config.get('webhooks', {})
            
            # Build clean webhooks dict
            webhooks = {}
            
            # Standard channel names
            for channel in ['breakout', 'position', 'market', 'system']:
                if webhooks_config.get(channel):
                    webhooks[channel] = webhooks_config[channel]
            
            # Legacy support: check for flat keys with _webhook_url suffix
            if not webhooks.get('breakout') and discord_config.get('breakout_webhook_url'):
                webhooks['breakout'] = discord_config['breakout_webhook_url']
            if not webhooks.get('position') and discord_config.get('position_webhook_url'):
                webhooks['position'] = discord_config['position_webhook_url']
            if not webhooks.get('market') and discord_config.get('market_webhook_url'):
                webhooks['market'] = discord_config['market_webhook_url']
            
            # Regime webhook as fallback for market channel
            if not webhooks.get('market'):
                if webhooks_config.get('regime_webhook_url'):
                    webhooks['market'] = webhooks_config['regime_webhook_url']
                elif discord_config.get('regime_webhook_url'):
                    webhooks['market'] = discord_config['regime_webhook_url']
            
            # Default webhook (fallback for any channel)
            default_webhook = discord_config.get('default_webhook') or discord_config.get('webhook_url')
            
            # Log what webhooks are configured
            self.logger.info(f"Discord webhooks configured: {list(webhooks.keys())}")
            self.logger.info(f"Discord default webhook: {'configured' if default_webhook else 'NOT configured'}")
            
            if not webhooks and not default_webhook:
                self.logger.warning("No Discord webhooks configured - alerts will not be sent")
                return
            
            self.discord_notifier = DiscordNotifier(
                webhooks=webhooks,
                default_webhook=default_webhook,
                logger=get_logger('discord')
            )
            self.logger.info("Discord notifier initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Discord: {e}")

    def _init_providers(self):
        """Initialize data providers via the provider abstraction layer.

        Reads provider configuration from the database.  On first run (no
        rows in ``provider_config``), seeds the DB from the YAML config so
        that existing setups migrate automatically.

        After this method the following are available:
        - ``self.historical_provider`` (new API) + ``self.polygon_client`` (legacy)
        - ``self.realtime_provider`` (wraps existing ibkr_client)
        - ``self.futures_provider`` (wraps existing ibkr_client)
        """
        if not self.db_session_factory:
            self.logger.warning("Provider init skipped — no database")
            return

        try:
            from ..providers import ProviderFactory

            self.provider_factory = ProviderFactory(self.db_session_factory)

            # Seed from YAML if provider_config table is empty
            session = self.db_session_factory()
            try:
                from ..data.models import ProviderConfig
                count = session.query(ProviderConfig).count()
            finally:
                session.close()

            if count == 0:
                self.logger.info("No provider config in DB — seeding from YAML")
                self.provider_factory.seed_from_yaml(self.config)

            # Create historical provider (Massive / Polygon)
            self.historical_provider = self.provider_factory.get_historical()

            if self.historical_provider:
                # Expose underlying PolygonClient for legacy consumers
                # (VolumeService, MaintenanceThread, EarningsService, TechnicalDataService)
                self.polygon_client = self.historical_provider.client
                self.logger.info(
                    "Historical provider '%s' ready (health=%s)",
                    self.historical_provider.name,
                    self.historical_provider.health.status.value,
                )
            else:
                self.logger.warning(
                    "No historical provider available — volume/earnings updates disabled"
                )

            # Wrap the existing IBKR client in provider abstractions.
            # This avoids creating a second IBKR connection — the providers
            # simply delegate to the already-connected ibkr_client.
            if self.ibkr_client:
                try:
                    from ..providers.ibkr import IBKRRealtimeProvider, IBKRFuturesProvider

                    self.realtime_provider = IBKRRealtimeProvider(
                        ibkr_client=self.ibkr_client,
                    )
                    self.futures_provider = IBKRFuturesProvider(
                        ibkr_client=self.ibkr_client,
                    )
                    self.logger.info("IBKR realtime + futures providers created (shared client)")
                except Exception as e:
                    self.logger.warning(f"Could not create IBKR providers: {e}")

        except Exception as e:
            self.logger.error(f"Failed to initialize providers: {e}", exc_info=True)

    def _init_scoring_engine(self):
        """Initialize the scoring engine for setup evaluation."""
        try:
            # Look for scoring config in multiple locations
            scoring_config_paths = [
                os.path.join(os.path.dirname(self.config_path or ''), 'scoring_config.yaml'),
                os.path.join(os.path.dirname(self.config_path or ''), 'config', 'scoring_config.yaml'),
                'scoring_config.yaml',
                'config/scoring_config.yaml',
            ]
            
            scoring_config_path = None
            for path in scoring_config_paths:
                if os.path.exists(path):
                    scoring_config_path = path
                    break
            
            if scoring_config_path:
                self.scoring_engine = ScoringEngine(config_path=scoring_config_path)
                self.logger.info(f"Scoring engine initialized: {scoring_config_path}")
            else:
                self.logger.warning(f"No scoring config found, scoring disabled. Searched: {scoring_config_paths[:3]}")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize scoring engine: {e}")
    
    def _init_position_sizer(self):
        """Initialize the position sizer for share calculations."""
        try:
            position_config = self.config.get('position_sizing', {})
            
            self.position_sizer = PositionSizer(
                account_risk_pct=position_config.get('account_risk_pct', 1.0),
                max_position_pct=position_config.get('max_position_pct', 10.0),
                initial_pct=position_config.get('initial_pct', 50.0),
                pyramid1_pct=position_config.get('pyramid1_pct', 25.0),
                pyramid2_pct=position_config.get('pyramid2_pct', 25.0),
            )
            self.logger.info("Position sizer initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize position sizer: {e}")
    
    def _init_alert_service(self):
        """Initialize the alert service for alert routing and persistence."""
        try:
            from ..utils.logging import get_logger
            
            alert_config = self.config.get('alerts', {})
            
            self.alert_service = AlertService(
                db_session_factory=self.db_session_factory,
                discord_notifier=self.discord_notifier,
                cooldown_minutes=alert_config.get('cooldown_minutes', 60),
                enable_cooldown=alert_config.get('enable_cooldown', False),
                enable_suppression=alert_config.get('enable_suppression', True),
                alert_routing=alert_config.get('alert_routing', {}),
                logger=get_logger('breakout')  # Use breakout logger so alerts appear in breakout log
            )
            self.logger.info(f"Alert service initialized (cooldown={'enabled' if alert_config.get('enable_cooldown', False) else 'disabled'}, discord={'configured' if self.discord_notifier else 'NOT configured'})")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize alert service: {e}")
    
    def _create_threads(self):
        """Create all worker threads."""
        # Import logger factory for thread loggers
        from ..utils.logging import get_logger
        
        thread_config = self.config.get('threads', {})
        alert_cfg = self.config.get('alerts', {})
        breakout_config = alert_cfg.get('breakout', {}) or self.config.get('breakout', {})
        
        # Create volume service for breakout thread (for intraday volume fallback)
        volume_service = None
        if self.polygon_client and self.db_session_factory:
            from ..services.volume_service import VolumeService
            volume_service = VolumeService(
                db_session_factory=self.db_session_factory,
                polygon_client=self.polygon_client,
                logger=get_logger('volume')
            )

        # Phase 2: Pass scoring engine, position sizer, and alert service to breakout thread
        # Merge breakout config with full config so thread has access to Polygon API key for MAs
        full_breakout_config = {**self.config, **breakout_config}
        self.threads['breakout'] = BreakoutThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('breakout_interval', 60),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=full_breakout_config,
            # Phase 2 dependencies
            scoring_engine=self.scoring_engine,
            position_sizer=self.position_sizer,
            alert_service=self.alert_service,
            # Volume service for intraday fallback
            volume_service=volume_service,
            # Provider abstraction layer (Phase 6)
            realtime_provider=self.realtime_provider,
            logger=get_logger('breakout')  # Use configured logger
        )

        self.threads['position'] = PositionThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('position_interval', 30),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=self.config,  # Pass full config for position_monitoring section
            # Provider abstraction layer (Phase 6)
            realtime_provider=self.realtime_provider,
            logger=get_logger('position')  # Use configured logger
        )

        # Use comprehensive RegimeThread (ported from MarketRegime-MonitorSystem)
        # Lazy import to avoid circular dependency
        from ..regime.regime_thread import RegimeThread

        self.threads['regime'] = RegimeThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('regime_interval', 300),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=self.config,
            # Provider abstraction layer (Phase 6)
            historical_provider=self.historical_provider,
            futures_provider=self.futures_provider,
            logger=get_logger('regime')  # Use configured logger
        )

        # Maintenance thread for nightly updates (volume, earnings, cleanup)
        if self.polygon_client or self.historical_provider:
            self.threads['maintenance'] = MaintenanceThread(
                shutdown_event=self.shutdown_event,
                poll_interval=thread_config.get('maintenance_interval', 300),  # Check every 5 min
                db_session_factory=self.db_session_factory,
                polygon_client=self.polygon_client,
                config=self.config,
                # Provider abstraction layer (Phase 6)
                historical_provider=self.historical_provider,
                logger=get_logger('maintenance')
            )
        else:
            self.logger.warning("Maintenance thread disabled - no Polygon client")

        # Inject shared MarketCalendar into all threads for holiday awareness
        if self.market_calendar:
            for thread in self.threads.values():
                thread._market_calendar = self.market_calendar

        self.logger.info(f"Created {len(self.threads)} threads (market_calendar={'yes' if self.market_calendar else 'no'})")
    
    def _start_ipc_server(self):
        """Start the IPC server for GUI communication."""
        self.pipe_server = create_pipe_server(
            command_queue=self.command_queue,
            shutdown_event=self.shutdown_event,
            command_handler=self._handle_ipc_command,
            logger=self.logger.getChild('ipc')
        )
        self.pipe_server.start()
        self.logger.info("IPC server started on \\\\.\\pipe\\CANSLIMMonitor")
    
    def _command_loop(self):
        """Main loop processing commands from queue."""
        while not self.shutdown_event.is_set():
            try:
                command = self.command_queue.get(timeout=1)
                result = self._process_command(command)
                # Results are handled directly by IPC server via command_handler
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error in command loop: {e}", exc_info=True)
    
    def _handle_ipc_command(self, command: dict) -> dict:
        """
        Handle IPC command directly (called by pipe server).
        
        This is the synchronous handler for IPC commands.
        """
        cmd_type = command.get('type', '')
        
        if cmd_type == 'GET_STATUS':
            return self._get_status()
        elif cmd_type == 'GET_STATS':
            return self._get_status()  # Alias
        elif cmd_type == 'RELOAD_CONFIG':
            return self._reload_config()
        elif cmd_type == 'FORCE_CHECK':
            return self._force_check(command.get('data', {}).get('symbol'))
        elif cmd_type == 'GET_REGIME':
            return self._get_regime()
        elif cmd_type == 'SHUTDOWN':
            return self._request_shutdown()
        else:
            return {'error': f'Unknown command: {cmd_type}'}
    
    def _process_command(self, command: dict) -> dict:
        """Process a command from the queue."""
        return self._handle_ipc_command(command)
    
    def _get_status(self) -> dict:
        """
        Get comprehensive service status.
        
        Returns status for GUI's ServiceStatusBar:
        - service_running: bool
        - uptime_seconds: float
        - threads: dict of thread status
        - ibkr_connected: bool
        - database_ok: bool
        """
        uptime = 0.0
        if self._start_time:
            uptime = (datetime.now() - self._start_time).total_seconds()
        
        # Gather thread status
        thread_status = {}
        for name, thread in self.threads.items():
            thread_status[name] = thread.get_stats()
        
        # Check IBKR connection status
        ibkr_connected = False
        if self.ibkr_client:
            try:
                # IBKRClient uses is_connected() method
                if hasattr(self.ibkr_client, 'is_connected'):
                    ibkr_connected = self.ibkr_client.is_connected()
                elif hasattr(self.ibkr_client, 'isConnected'):
                    # Fallback for raw IB object
                    ibkr_connected = self.ibkr_client.isConnected()
            except Exception:
                ibkr_connected = False
        
        return {
            'service_running': self._is_running,
            'uptime_seconds': uptime,
            'threads': thread_status,
            'ibkr_connected': ibkr_connected,
            'database_ok': self.db_session_factory is not None,
            'timestamp': datetime.now().isoformat()
        }
    
    def _get_regime(self) -> dict:
        """Get current market regime status."""
        regime_thread = self.threads.get('regime')
        if regime_thread:
            return {
                'regime': regime_thread.get_current_regime(),
                'exposure': regime_thread.get_exposure_recommendation(),
            }
        return {'regime': None, 'exposure': (50, 75)}
    
    def _reload_config(self) -> dict:
        """Reload configuration from file."""
        try:
            self._load_config()

            # Refresh alert routing on live AlertService instances
            alert_routing = self.config.get('alerts', {}).get('alert_routing', {})
            if hasattr(self, 'alert_service') and self.alert_service:
                self.alert_service.load_routing(alert_routing)
            # Also refresh position thread's AlertService
            if hasattr(self, 'position_thread') and self.position_thread:
                if hasattr(self.position_thread, 'alert_service') and self.position_thread.alert_service:
                    self.position_thread.alert_service.load_routing(alert_routing)

            return {'success': True, 'message': 'Configuration reloaded'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _force_check(self, symbol: str = None) -> dict:
        """Force an immediate check cycle."""
        # This could trigger an immediate check on specific threads
        return {'success': True, 'message': f'Force check triggered for {symbol or "all"}'}
    
    def _request_shutdown(self) -> dict:
        """
        Handle SHUTDOWN IPC command.
        
        Gracefully shuts down the service via IPC - doesn't require admin privileges.
        The service will stop itself cleanly.
        """
        self.logger.info("Shutdown requested via IPC")
        
        # Signal shutdown - this will cause the main run loop to exit
        self.shutdown_event.set()
        
        return {
            'success': True, 
            'message': 'Shutdown initiated'
        }
    
    def _cleanup(self):
        """Clean up resources on shutdown."""
        # Disconnect providers (historical, and future realtime/futures)
        if self.provider_factory:
            try:
                self.provider_factory.disconnect_all()
                self.logger.info("Providers disconnected")
            except Exception as e:
                self.logger.warning(f"Error disconnecting providers: {e}")

        # Disconnect IBKR
        if self.ibkr_client:
            try:
                # IBKRClient uses is_connected() method
                if hasattr(self.ibkr_client, 'is_connected'):
                    if self.ibkr_client.is_connected():
                        self.ibkr_client.disconnect()
                        self.logger.info("IBKR disconnected")
                elif hasattr(self.ibkr_client, 'isConnected'):
                    # Fallback for raw IB object
                    if self.ibkr_client.isConnected():
                        self.ibkr_client.disconnect()
                        self.logger.info("IBKR disconnected")
            except Exception as e:
                self.logger.warning(f"Error disconnecting IBKR: {e}")

        self.logger.debug("Cleanup complete")
    
    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running
    
    @property
    def uptime(self) -> float:
        """Get service uptime in seconds."""
        if self._start_time:
            return (datetime.now() - self._start_time).total_seconds()
        return 0.0


def run_standalone(config_path: str = None, db_path: str = None):
    """
    Run the service controller in standalone (console) mode.
    
    This is the entry point for `python -m canslim_monitor service`.
    Blocks until Ctrl+C is pressed.
    
    Args:
        config_path: Path to config file (optional)
        db_path: Path to database file (optional)
    """
    import signal
    
    # Setup logging for console
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    logger = logging.getLogger('canslim.service')
    
    # Create controller
    controller = ServiceController(
        config_path=config_path,
        db_path=db_path,
        logger=logger
    )
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        logger.info("\nShutdown requested (Ctrl+C)...")
        controller.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the service (blocks in command loop)
        controller.start()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested (Ctrl+C)...")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
    finally:
        controller.shutdown()
        logger.info("Service stopped")
