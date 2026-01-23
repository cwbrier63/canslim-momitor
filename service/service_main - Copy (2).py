"""
CANSLIM Monitor - Service Entry Point
=====================================
CLI entry point for running service in foreground or as Windows service.

FIXED VERSION - Integrates proper file-based logging from utils/logging.py

Usage:
    python -m canslim_monitor.service.service_main run          # Foreground mode
    python -m canslim_monitor.service.service_main install      # Install as service
    python -m canslim_monitor.service.service_main start        # Start service
    python -m canslim_monitor.service.service_main stop         # Stop service
    python -m canslim_monitor.service.service_main remove       # Remove service
"""

import argparse
import logging
import os
import signal
import sys
import traceback
from pathlib import Path
from datetime import datetime

# CRITICAL: Add the Trading directory to sys.path for Windows service
# Services run from C:\Windows\System32, so they can't find canslim_monitor
TRADING_DIR = r"C:\Trading"
if TRADING_DIR not in sys.path:
    sys.path.insert(0, TRADING_DIR)

# Default log directory - create early for startup error logging
DEFAULT_LOG_DIR = Path(r"C:\Trading\canslim_monitor\logs")

def write_startup_error(error_msg: str, exc_info=None):
    """
    Write startup errors to a fallback log file.
    This is called BEFORE the logging system is initialized.
    """
    try:
        DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        error_file = DEFAULT_LOG_DIR / "startup_errors.log"
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(error_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{timestamp}] STARTUP ERROR\n")
            f.write(f"{'='*60}\n")
            f.write(f"{error_msg}\n")
            if exc_info:
                f.write("\nTraceback:\n")
                f.write(traceback.format_exc())
            f.write("\n")
    except Exception as e:
        # Last resort - try Windows event log
        pass


# Try to import Windows service utilities
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_WIN32SERVICE = True
except ImportError as e:
    HAS_WIN32SERVICE = False
    write_startup_error(f"win32service import failed: {e}", exc_info=True)


def setup_logging_with_files(config: dict = None) -> logging.Logger:
    """
    Set up logging using the full LoggingManager with file handlers.
    
    This replaces the simple console-only setup with proper file logging.
    """
    try:
        # Import the logging facility
        from canslim_monitor.utils.logging import setup_logging as setup_file_logging, get_logger
        
        # Get log directory from config or use default
        log_dir = DEFAULT_LOG_DIR
        if config:
            log_config = config.get('logging', {})
            if log_config.get('base_dir'):
                log_dir = Path(log_config['base_dir'])
        
        # Ensure log directory exists
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize the logging manager
        console_level = logging.INFO
        if config:
            level_str = config.get('logging', {}).get('console_level', 'INFO')
            console_level = getattr(logging, level_str.upper(), logging.INFO)
        
        setup_file_logging(
            log_dir=str(log_dir),
            console_level=console_level,
            retention_days=30
        )
        
        # Get the service logger
        logger = get_logger('service')
        logger.info(f"Logging initialized - log directory: {log_dir}")
        
        return logger
        
    except Exception as e:
        write_startup_error(f"Failed to initialize file logging: {e}", exc_info=True)
        
        # Fallback to basic console logging
        logger = logging.getLogger('canslim')
        logger.setLevel(logging.DEBUG)
        
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        logger.warning(f"Using fallback console logging due to error: {e}")
        return logger


def find_config_file(explicit_path: str = None) -> str:
    """Find configuration file."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path
    
    # Search paths - use TRADING_DIR for service context
    search_paths = [
        os.path.join(TRADING_DIR, 'canslim_monitor', 'user_config.yaml'),
        os.path.join(TRADING_DIR, 'user_config.yaml'),
        os.path.join(TRADING_DIR, 'config.yaml'),
        'user_config.yaml',
        'config.yaml',
        os.path.join(os.getcwd(), 'user_config.yaml'),
        os.path.join(os.getcwd(), 'canslim_monitor', 'user_config.yaml'),
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    return None


def find_database_file(explicit_path: str = None) -> str:
    """Find database file."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path
    
    # Search paths - use TRADING_DIR for service context
    search_paths = [
        os.path.join(TRADING_DIR, 'canslim_monitor', 'canslim_monitor.db'),
        os.path.join(TRADING_DIR, 'canslim_positions.db'),
        os.path.join(TRADING_DIR, 'canslim_monitor.db'),
        'canslim_monitor.db',
        'canslim_positions.db',
        os.path.join(os.getcwd(), 'canslim_monitor.db'),
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    return None


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    if not config_path:
        return {}
    
    try:
        import yaml
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        write_startup_error(f"Failed to load config from {config_path}: {e}", exc_info=True)
        return {}


def run_foreground(config_path: str = None, db_path: str = None):
    """Run service in foreground mode (not as Windows service)."""
    try:
        # Find and load config first
        config_path = find_config_file(config_path)
        config = load_config(config_path)
        
        # Set up logging with file handlers
        logger = setup_logging_with_files(config)
        
        logger.info("=" * 60)
        logger.info("CANSLIM Monitor Service - Foreground Mode")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C to stop")
        
        # Find database
        db_path = find_database_file(db_path)
        
        logger.info(f"Config: {config_path or 'not found'}")
        logger.info(f"Database: {db_path or 'not found'}")
        
        # Import controller after logging is set up
        from canslim_monitor.service.service_controller import ServiceController
        
        # Create controller
        controller = ServiceController(
            config_path=config_path,
            db_path=db_path,
            logger=logger
        )
        
        # Handle Ctrl+C
        def signal_handler(signum, frame):
            logger.info("\nReceived shutdown signal...")
            controller.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start service
        logger.info("Starting service threads...")
        controller.start()
        
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt received")
        if 'controller' in locals():
            controller.shutdown()
    except Exception as e:
        write_startup_error(f"Service error in foreground mode: {e}", exc_info=True)
        if 'logger' in locals():
            logger.error(f"Service error: {e}", exc_info=True)
        if 'controller' in locals():
            controller.shutdown()
        sys.exit(1)


if HAS_WIN32SERVICE:
    class CANSLIMMonitorService(win32serviceutil.ServiceFramework):
        """Windows Service wrapper for CANSLIM Monitor."""
        
        _svc_name_ = "CANSLIMMonitor"
        _svc_display_name_ = "CANSLIM Monitor Service"
        _svc_description_ = "Monitors CANSLIM watchlist for breakouts and position alerts"
        
        def __init__(self, args):
            try:
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.stop_event = win32event.CreateEvent(None, 0, 0, None)
                self.controller = None
                self.logger = None
            except Exception as e:
                write_startup_error(f"Service __init__ failed: {e}", exc_info=True)
                raise
        
        def SvcStop(self):
            """Handle service stop request."""
            try:
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                win32event.SetEvent(self.stop_event)
                
                if self.controller:
                    self.controller.shutdown()
            except Exception as e:
                write_startup_error(f"Service SvcStop error: {e}", exc_info=True)
        
        def SvcDoRun(self):
            """Handle service start."""
            try:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, '')
                )
                self.main()
            except Exception as e:
                write_startup_error(f"Service SvcDoRun failed: {e}", exc_info=True)
                servicemanager.LogErrorMsg(f"Service failed to start: {e}")
                raise
        
        def main(self):
            """Main service execution."""
            try:
                # Change to Trading directory
                os.chdir(TRADING_DIR)
                write_startup_error(f"Changed working directory to: {os.getcwd()}")
                
                # Find and load config BEFORE setting up logging
                config_path = find_config_file()
                write_startup_error(f"Config path found: {config_path}")
                
                config = load_config(config_path)
                
                # Set up logging with file handlers
                self.logger = setup_logging_with_files(config)
                
                self.logger.info("=" * 60)
                self.logger.info("CANSLIM Monitor Service starting (Windows Service mode)")
                self.logger.info("=" * 60)
                
                # Find database
                db_path = find_database_file()
                
                self.logger.info(f"Config: {config_path}")
                self.logger.info(f"Database: {db_path}")
                self.logger.info(f"Working directory: {os.getcwd()}")
                
                # Import controller
                from canslim_monitor.service.service_controller import ServiceController
                
                self.controller = ServiceController(
                    config_path=config_path,
                    db_path=db_path,
                    logger=self.logger
                )
                
                # Start in a separate thread so we can wait for stop event
                import threading
                service_thread = threading.Thread(target=self.controller.start)
                service_thread.start()
                
                self.logger.info("Service thread started, waiting for stop signal...")
                
                # Wait for stop signal
                win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
                
                # Shutdown
                self.logger.info("Stop signal received, shutting down...")
                self.controller.shutdown()
                service_thread.join(timeout=10)
                
                self.logger.info("Service stopped successfully")
                
            except Exception as e:
                write_startup_error(f"Service main() error: {e}", exc_info=True)
                if self.logger:
                    self.logger.error(f"Service main() error: {e}", exc_info=True)
                raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='CANSLIM Monitor Service')
    parser.add_argument(
        'command',
        choices=['run', 'install', 'start', 'stop', 'remove', 'status', 'debug'],
        help='Service command'
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to config file'
    )
    parser.add_argument(
        '-d', '--database',
        help='Path to database file'
    )
    
    args = parser.parse_args()
    
    if args.command in ('run', 'debug'):
        # Run in foreground mode
        run_foreground(config_path=args.config, db_path=args.database)
        
    elif args.command in ('install', 'start', 'stop', 'remove'):
        if not HAS_WIN32SERVICE:
            print("Error: Windows service utilities not available")
            print("Install pywin32: pip install pywin32")
            sys.exit(1)
        
        # Pass to Windows service handler
        if args.command == 'install':
            win32serviceutil.HandleCommandLine(
                CANSLIMMonitorService,
                argv=['', 'install']
            )
        elif args.command == 'start':
            win32serviceutil.HandleCommandLine(
                CANSLIMMonitorService,
                argv=['', 'start']
            )
        elif args.command == 'stop':
            win32serviceutil.HandleCommandLine(
                CANSLIMMonitorService,
                argv=['', 'stop']
            )
        elif args.command == 'remove':
            win32serviceutil.HandleCommandLine(
                CANSLIMMonitorService,
                argv=['', 'remove']
            )
            
    elif args.command == 'status':
        # Check service status
        try:
            from canslim_monitor.service.ipc import PipeClient
            
            client = PipeClient()
            if client.connect(timeout=1.0):
                status = client.get_status()
                client.disconnect()
                
                if status:
                    print("Service Status: RUNNING")
                    print(f"  Uptime: {status.get('uptime_seconds', 0):.0f} seconds")
                    print(f"  IBKR: {'Connected' if status.get('ibkr_connected') else 'Not connected'}")
                    print(f"  Database: {'OK' if status.get('database_ok') else 'Not connected'}")
                    print("\nThreads:")
                    for name, info in status.get('threads', {}).items():
                        state = info.get('state', 'unknown')
                        msgs = info.get('message_count', 0)
                        errors = info.get('error_count', 0)
                        print(f"  {name}: {state} (messages: {msgs}, errors: {errors})")
                else:
                    print("Service Status: RUNNING (but not responding)")
            else:
                print("Service Status: NOT RUNNING")
        except Exception as e:
            print(f"Error checking status: {e}")
        

if __name__ == '__main__':
    main()
