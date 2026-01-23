"""
CANSLIM Monitor - Position Management System
A comprehensive CANSLIM trading system with real-time monitoring.

Usage:
    python -m canslim_monitor gui              # Launch Kanban GUI
    python -m canslim_monitor import <file>    # Import from Excel
    python -m canslim_monitor service          # Run monitoring service
"""

__version__ = '0.3.0'
__author__ = 'CANSLIM Monitor Project'


def get_database_manager():
    """Lazy import of DatabaseManager."""
    from canslim_monitor.data.database import DatabaseManager
    return DatabaseManager


def get_repository_manager():
    """Lazy import of RepositoryManager."""
    from canslim_monitor.data.repositories import RepositoryManager
    return RepositoryManager


def init_database(db_path: str):
    """Initialize database at given path."""
    from canslim_monitor.data.database import init_database as _init
    return _init(db_path)


__all__ = [
    '__version__',
    'get_database_manager',
    'get_repository_manager', 
    'init_database',
]
