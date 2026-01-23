"""
CANSLIM Monitor - Service Entry Point
CLI entry point for running service in foreground or as Windows service.

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
from pathlib import Path

# CRITICAL: Add the Trading directory to sys.path for Windows service
# Services run from C:\Windows\System32, so they can't find canslim_monitor
TRADING_DIR = r"C:\Trading"
if TRADING_DIR not in sys.path:
    sys.path.insert(0, TRADING_DIR)

# Try to import Windows service utilities
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_WIN32SERVICE = True
except ImportError:
    HAS_WIN32SERVICE = False


def setup_logging(log_level: str = 'INFO') -> logging.Logger:
    """Set up logging for the service."""
    logger = logging.getLogger('canslim')
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger


def find_config_file(explicit_path: str = None) -> str:
    """Find configuration file."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path
    
    # Search paths - use TRADING_DIR for service context
    search_paths = [
        os.path.join(TRADING_DIR, 'user_config.yaml'),
        os.path.join(TRADING_DIR, 'config.yaml'),
        os.path.join(TRADING_DIR, 'canslim_monitor', 'user_config.yaml'),
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
        os.path.join(TRADING_DIR, 'canslim_positions.db'),
        'canslim_positions.db',
        os.path.join(os.getcwd(), 'canslim_positions.db'),
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    return None


def run_foreground(config_path: str = None, db_path: str = None):
    """Run service in foreground mode (not as Windows service)."""
    from .service_controller import ServiceController
    
    logger = setup_logging()
    logger.info("CANSLIM Monitor Service - Foreground Mode")
    logger.info("Press Ctrl+C to stop")
    
    # Find config and database
    config_path = find_config_file(config_path)
    db_path = find_database_file(db_path)
    
    logger.info(f"Config: {config_path or 'not found'}")
    logger.info(f"Database: {db_path or 'not found'}")
    
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
    try:
        logger.info("Service started. Threads running...")
        controller.start()
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt received")
        controller.shutdown()
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        controller.shutdown()
        sys.exit(1)


if HAS_WIN32SERVICE:
    class CANSLIMMonitorService(win32serviceutil.ServiceFramework):
        """Windows Service wrapper for CANSLIM Monitor."""
        
        _svc_name_ = "CANSLIMMonitor"
        _svc_display_name_ = "CANSLIM Monitor Service"
        _svc_description_ = "Monitors CANSLIM watchlist for breakouts and position alerts"
        
        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.controller = None
            self.logger = None
        
        def SvcStop(self):
            """Handle service stop request."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            
            if self.controller:
                self.controller.shutdown()
        
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
                servicemanager.LogErrorMsg(f"Service failed to start: {e}")
                raise
        
        def main(self):
            """Main service execution."""
            # Change to Trading directory
            os.chdir(TRADING_DIR)
            
            # Import here after path is set
            from canslim_monitor.service.service_controller import ServiceController
            
            self.logger = setup_logging()
            self.logger.info("CANSLIM Monitor Service starting...")
            
            # Find config and database
            config_path = find_config_file()
            db_path = find_database_file()
            
            self.logger.info(f"Config: {config_path}")
            self.logger.info(f"Database: {db_path}")
            
            self.controller = ServiceController(
                config_path=config_path,
                db_path=db_path,
                logger=self.logger
            )
            
            # Start in a separate thread so we can wait for stop event
            import threading
            service_thread = threading.Thread(target=self.controller.start)
            service_thread.start()
            
            # Wait for stop signal
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            
            # Shutdown
            self.controller.shutdown()
            service_thread.join(timeout=10)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='CANSLIM Monitor Service')
    parser.add_argument(
        'command',
        choices=['run', 'install', 'start', 'stop', 'remove', 'status'],
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
    
    if args.command == 'run':
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
        from .ipc import PipeClient
        
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
        

if __name__ == '__main__':
    main()
