"""
CANSLIM Monitor - Logging Facility
Phase 1: Database Foundation

Provides comprehensive logging with:
- Daily log rotation
- Category-based logging (service, threads, integrations, database, gui)
- Combined log and errors-only log
- Configurable log levels per category
- Structured log format
"""

import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import yaml


# Log format: [TIMESTAMP] [LEVEL] [THREAD] [MODULE] - MESSAGE
LOG_FORMAT = '[%(asctime)s.%(msecs)03d] [%(levelname)-8s] [%(threadName)-15s] [%(name)-20s] - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Default log directory
DEFAULT_LOG_DIR = os.path.join(
    os.environ.get('CANSLIM_DATA_DIR', 'C:/Trading/CANSLIM Watch List Monitor'),
    'logs'
)

# Log categories and their subdirectories
LOG_CATEGORIES = {
    'service': 'service',
    'breakout': 'threads',
    'position': 'threads',
    'market': 'threads',
    'ibkr': 'integrations',
    'discord': 'integrations',
    'sheets': 'integrations',
    'polygon': 'integrations',
    'database': 'database',
    'gui': 'gui',
}

# Default log levels per category
DEFAULT_LOG_LEVELS = {
    'service': logging.DEBUG,
    'breakout': logging.DEBUG,
    'position': logging.DEBUG,
    'market': logging.DEBUG,
    'ibkr': logging.DEBUG,
    'discord': logging.DEBUG,
    'sheets': logging.DEBUG,
    'polygon': logging.DEBUG,
    'database': logging.INFO,
    'gui': logging.INFO,
}


class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    Custom handler that creates daily log files with date in filename.
    Format: category_YYYY-MM-DD.log
    """
    
    def __init__(
        self,
        log_dir: str,
        category: str,
        level: int = logging.DEBUG,
        retention_days: int = 30
    ):
        """
        Initialize daily rotating handler.
        
        Args:
            log_dir: Directory for log files
            category: Log category name
            level: Log level
            retention_days: Number of days to retain logs
        """
        self.log_dir = Path(log_dir)
        self.category = category
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initial log file path
        log_file = self._get_log_filename()
        
        super().__init__(
            log_file,
            when='midnight',
            interval=1,
            backupCount=retention_days,
            encoding='utf-8'
        )
        
        self.setLevel(level)
        self.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    
    def _get_log_filename(self) -> str:
        """Get log filename for today."""
        today = datetime.now().strftime('%Y-%m-%d')
        return str(self.log_dir / f"{self.category}_{today}.log")
    
    def doRollover(self):
        """Override rollover to use date-based naming."""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Update to new date-based filename
        self.baseFilename = self._get_log_filename()
        
        # Cleanup old files
        self._cleanup_old_logs()
        
        # Open new file
        self.mode = 'a'
        self.stream = self._open()
    
    def _cleanup_old_logs(self):
        """Remove logs older than retention period."""
        import glob
        from datetime import timedelta
        
        pattern = str(self.log_dir / f"{self.category}_*.log")
        cutoff = datetime.now() - timedelta(days=self.backupCount)
        
        for log_file in glob.glob(pattern):
            try:
                # Extract date from filename
                filename = os.path.basename(log_file)
                date_str = filename.replace(f"{self.category}_", "").replace(".log", "")
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                
                if file_date < cutoff:
                    os.remove(log_file)
            except (ValueError, OSError):
                pass


class LoggingManager:
    """
    Manages application-wide logging configuration.
    Creates category-specific loggers with daily rotation.
    """
    
    def __init__(
        self,
        log_dir: str = None,
        config_file: str = None,
        console_level: int = logging.INFO,
        retention_days: int = 30
    ):
        """
        Initialize logging manager.
        
        Args:
            log_dir: Base directory for log files
            config_file: Path to logging config YAML file
            console_level: Log level for console output
            retention_days: Number of days to retain logs
        """
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.console_level = console_level
        self.retention_days = retention_days
        self.loggers: Dict[str, logging.Logger] = {}
        self.handlers: Dict[str, logging.Handler] = {}
        
        # Load config if provided
        self.config = {}
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        
        # Create log directory structure
        self._create_directory_structure()
        
        # Initialize combined log handlers
        self._setup_combined_logs()
        
        # Set up console handler
        self._setup_console_handler()
    
    def _create_directory_structure(self):
        """Create the log directory structure."""
        subdirs = set(LOG_CATEGORIES.values())
        subdirs.add('combined')
        
        for subdir in subdirs:
            Path(self.log_dir, subdir).mkdir(parents=True, exist_ok=True)
    
    def _setup_combined_logs(self):
        """Set up combined log handlers (all logs and errors only)."""
        combined_dir = os.path.join(self.log_dir, 'combined')
        
        # All logs combined
        self.handlers['combined_all'] = DailyRotatingFileHandler(
            combined_dir, 'all',
            level=logging.DEBUG,
            retention_days=self.retention_days
        )
        
        # Errors only
        self.handlers['combined_errors'] = DailyRotatingFileHandler(
            combined_dir, 'errors',
            level=logging.ERROR,
            retention_days=self.retention_days
        )
    
    def _setup_console_handler(self):
        """Set up console output handler."""
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(self.console_level)
        console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        self.handlers['console'] = console
    
    def get_logger(self, category: str) -> logging.Logger:
        """
        Get a logger for a specific category.
        
        Args:
            category: Logger category (service, breakout, position, etc.)
        
        Returns:
            Configured Logger instance
        """
        if category in self.loggers:
            return self.loggers[category]
        
        # Create logger
        logger = logging.getLogger(f'canslim.{category}')
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        
        # Get log level from config or defaults
        level = self.config.get('levels', {}).get(
            category,
            DEFAULT_LOG_LEVELS.get(category, logging.DEBUG)
        )
        
        # Determine subdirectory
        subdir = LOG_CATEGORIES.get(category, category)
        log_dir = os.path.join(self.log_dir, subdir)
        
        # Create category-specific handler
        handler = DailyRotatingFileHandler(
            log_dir, category,
            level=level,
            retention_days=self.retention_days
        )
        logger.addHandler(handler)
        
        # Add combined handlers
        logger.addHandler(self.handlers['combined_all'])
        logger.addHandler(self.handlers['combined_errors'])
        
        # Add console handler
        logger.addHandler(self.handlers['console'])
        
        self.loggers[category] = logger
        return logger
    
    def set_level(self, category: str, level: int):
        """
        Set log level for a category.
        
        Args:
            category: Logger category
            level: New log level
        """
        if category in self.loggers:
            for handler in self.loggers[category].handlers:
                if isinstance(handler, DailyRotatingFileHandler):
                    handler.setLevel(level)
    
    def set_console_level(self, level: int):
        """Set console output log level."""
        if 'console' in self.handlers:
            self.handlers['console'].setLevel(level)
    
    def shutdown(self):
        """Shutdown all loggers and handlers."""
        for logger in self.loggers.values():
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
        
        self.loggers.clear()
        self.handlers.clear()


# Global logging manager instance
_logging_manager: Optional[LoggingManager] = None


def setup_logging(
    log_dir: str = None,
    config_file: str = None,
    console_level: int = logging.INFO,
    retention_days: int = 30
) -> LoggingManager:
    """
    Initialize the global logging manager.
    
    Args:
        log_dir: Base directory for log files
        config_file: Path to logging config YAML file
        console_level: Log level for console output
        retention_days: Number of days to retain logs
    
    Returns:
        LoggingManager instance
    """
    global _logging_manager
    
    _logging_manager = LoggingManager(
        log_dir=log_dir,
        config_file=config_file,
        console_level=console_level,
        retention_days=retention_days
    )
    
    return _logging_manager


def get_logger(category: str) -> logging.Logger:
    """
    Get a logger for a specific category.
    
    Args:
        category: Logger category
    
    Returns:
        Logger instance
    """
    global _logging_manager
    
    if _logging_manager is None:
        setup_logging()
    
    return _logging_manager.get_logger(category)


def shutdown_logging():
    """Shutdown the logging system."""
    global _logging_manager
    
    if _logging_manager:
        _logging_manager.shutdown()
        _logging_manager = None


# Convenience functions for getting specific loggers
def get_service_logger() -> logging.Logger:
    """Get the service logger."""
    return get_logger('service')


def get_breakout_logger() -> logging.Logger:
    """Get the breakout thread logger."""
    return get_logger('breakout')


def get_position_logger() -> logging.Logger:
    """Get the position thread logger."""
    return get_logger('position')


def get_market_logger() -> logging.Logger:
    """Get the market thread logger."""
    return get_logger('market')


def get_ibkr_logger() -> logging.Logger:
    """Get the IBKR integration logger."""
    return get_logger('ibkr')


def get_discord_logger() -> logging.Logger:
    """Get the Discord integration logger."""
    return get_logger('discord')


def get_sheets_logger() -> logging.Logger:
    """Get the Google Sheets integration logger."""
    return get_logger('sheets')


def get_database_logger() -> logging.Logger:
    """Get the database logger."""
    return get_logger('database')


def get_gui_logger() -> logging.Logger:
    """Get the GUI logger."""
    return get_logger('gui')
