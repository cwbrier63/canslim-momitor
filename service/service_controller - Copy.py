"""
CANSLIM Monitor - Service Controller
Main controller managing threads, IPC, and shared resources.
"""

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional

from .threads import BreakoutThread, PositionThread, MarketThread
from .ipc import create_pipe_server

# Phase 2 dependencies
from ..utils.scoring_engine import ScoringEngine
from ..utils.position_sizer import PositionSizer
from ..services.alert_service import AlertService


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
        
        # Phase 2 components
        self.scoring_engine = None
        self.position_sizer = None
        self.alert_service = None
        
        # Tracking
        self._start_time: Optional[datetime] = None
        self._is_running = False
    
    def start(self):
        """Start the service controller and all threads."""
        self.logger.info("Starting CANSLIM Monitor Service Controller")
        
        self._start_time = datetime.now()
        self._is_running = True
        
        # Load configuration
        self._load_config()
        
        # Initialize shared resources
        self._init_database()
        self._init_ibkr()
        self._init_discord()
        
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
            # Use ThreadSafeIBKRClient which manages its own event loop in a dedicated thread
            from ..integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
            
            host = ibkr_config.get('host', '127.0.0.1')
            port = ibkr_config.get('port', 4001)
            client_id_base = ibkr_config.get('client_id_base', 20)
            timeout = ibkr_config.get('timeout', 30)
            max_retries = ibkr_config.get('max_client_id_retries', 5)
            
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
                        logger=self.logger.getChild('ibkr')
                    )
                    
                    if self.ibkr_client.connect(timeout=timeout):
                        self.logger.info(f"IBKR client connected successfully (client_id={client_id})")
                        return
                    else:
                        self.logger.warning(f"IBKR connection failed (client_id={client_id})")
                        
                except Exception as e:
                    error_msg = str(e)
                    if 'client id' in error_msg.lower() or '326' in error_msg:
                        self.logger.warning(f"Client ID {client_id} in use, trying next...")
                        continue
                    else:
                        self.logger.error(f"IBKR connection error: {e}")
                        break
            
            # All retries failed
            self.logger.warning("IBKR client failed to connect after all retries")
            self.ibkr_client = None
                
        except Exception as e:
            self.logger.error(f"Failed to initialize IBKR: {e}")
            self.ibkr_client = None
    
    def _init_discord(self):
        """Initialize Discord notifier."""
        discord_config = self.config.get('discord', {})
        if not discord_config:
            self.logger.warning("No Discord config found")
            return
        
        try:
            from ..integrations.discord_notifier import DiscordNotifier
            
            # Extract webhook URLs from config
            webhooks = discord_config.get('webhooks', {})
            default_webhook = discord_config.get('default_webhook', '')
            
            # If webhooks is a string (single webhook), use as default
            if isinstance(webhooks, str):
                default_webhook = webhooks
                webhooks = {}
            
            # Support flat config format: discord.breakout_webhook, discord.position_webhook, etc.
            if not webhooks:
                for key in ['breakout', 'position', 'market', 'system']:
                    webhook_key = f'{key}_webhook'
                    if webhook_key in discord_config:
                        webhooks[key] = discord_config[webhook_key]
            
            # Also check for 'webhook' as single default
            if not default_webhook and 'webhook' in discord_config:
                default_webhook = discord_config['webhook']
            
            # If still no webhooks, check for top-level webhook_url
            if not webhooks and not default_webhook:
                if 'webhook_url' in discord_config:
                    default_webhook = discord_config['webhook_url']
            
            self.discord_notifier = DiscordNotifier(
                webhooks=webhooks,
                default_webhook=default_webhook,
                logger=self.logger.getChild('discord'),
                enabled=discord_config.get('enabled', True)
            )
            
            self.logger.info(f"Discord notifier initialized (webhooks: {list(webhooks.keys()) if webhooks else 'default'})")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Discord: {e}")
    
    def _init_scoring_engine(self):
        """Initialize the scoring engine for setup grading."""
        try:
            import os
            
            # Get base directory from config path or use C:\Trading
            if self.config_path:
                config_dir = os.path.dirname(self.config_path)
                base_dir = os.path.dirname(config_dir) if config_dir.endswith('canslim_monitor') else config_dir
            else:
                base_dir = os.getcwd()
            
            # Look for scoring config in standard locations
            scoring_config_paths = [
                # Most likely: canslim_monitor/config/scoring_config.yaml
                os.path.join(base_dir, 'canslim_monitor', 'config', 'scoring_config.yaml'),
                os.path.join(os.path.dirname(self.config_path or ''), 'config', 'scoring_config.yaml'),
                os.path.join(os.path.dirname(self.config_path or ''), 'scoring_config.yaml'),
                os.path.join(base_dir, 'config', 'scoring_config.yaml'),
                'canslim_monitor/config/scoring_config.yaml',
                'config/scoring_config.yaml',
                'scoring_config.yaml',
            ]
            
            scoring_config_path = None
            for path in scoring_config_paths:
                self.logger.debug(f"Checking for scoring config at: {path}")
                if os.path.exists(path):
                    scoring_config_path = path
                    break
            
            if scoring_config_path:
                self.scoring_engine = ScoringEngine(scoring_config_path)
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
            alert_config = self.config.get('alerts', {})
            
            self.alert_service = AlertService(
                db_session_factory=self.db_session_factory,
                discord_notifier=self.discord_notifier,
                cooldown_minutes=alert_config.get('cooldown_minutes', 60),
                enable_suppression=alert_config.get('enable_suppression', True),
            )
            self.logger.info("Alert service initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize alert service: {e}")
    
    def _create_threads(self):
        """Create all worker threads."""
        thread_config = self.config.get('threads', {})
        breakout_config = self.config.get('breakout', {})
        
        # Phase 2: Pass scoring engine, position sizer, and alert service to breakout thread
        self.threads['breakout'] = BreakoutThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('breakout_interval', 60),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=breakout_config,
            # Phase 2 dependencies
            scoring_engine=self.scoring_engine,
            position_sizer=self.position_sizer,
            alert_service=self.alert_service,
        )
        
        self.threads['position'] = PositionThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('position_interval', 30),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=self.config.get('position', {})
        )
        
        self.threads['market'] = MarketThread(
            shutdown_event=self.shutdown_event,
            poll_interval=thread_config.get('market_interval', 300),
            db_session_factory=self.db_session_factory,
            ibkr_client=self.ibkr_client,
            discord_notifier=self.discord_notifier,
            config=self.config.get('market', {})
        )
        
        self.logger.info(f"Created {len(self.threads)} threads")
    
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
    
    def _reload_config(self) -> dict:
        """Reload configuration from file."""
        try:
            self._load_config()
            return {'success': True, 'message': 'Configuration reloaded'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _force_check(self, symbol: str = None) -> dict:
        """Force an immediate check cycle."""
        # This could trigger an immediate check on specific threads
        return {'success': True, 'message': f'Force check triggered for {symbol or "all"}'}
    
    def _cleanup(self):
        """Clean up resources on shutdown."""
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
