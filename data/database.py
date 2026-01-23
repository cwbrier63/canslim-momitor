"""
CANSLIM Monitor - Database Connection Management
Phase 1: Database Foundation

Handles SQLite connection, session management, and database initialization.
"""

import os
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional
from datetime import datetime
import shutil

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from canslim_monitor.data.models import Base, seed_default_config


class DatabaseManager:
    """
    Manages SQLite database connections and sessions.
    Implements WAL mode for better concurrency and performance.
    """
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        echo: bool = False,
        in_memory: bool = False
    ):
        """
        Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file. 
                     Defaults to 'canslim_monitor.db' in the application directory.
            echo: If True, log all SQL statements (useful for debugging)
            in_memory: If True, use an in-memory database (for testing)
        """
        if in_memory:
            self.db_path = ":memory:"
            self.engine = create_engine(
                "sqlite:///:memory:",
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool
            )
        else:
            if db_path is None:
                # Default to application directory
                db_path = os.path.join(
                    os.environ.get('CANSLIM_DATA_DIR', '.'),
                    'canslim_monitor.db'
                )
            self.db_path = db_path
            
            # Ensure directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            self.engine = create_engine(
                f"sqlite:///{self.db_path}",
                echo=echo,
                connect_args={"check_same_thread": False}
            )
        
        # Enable WAL mode and foreign keys on connection
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=10000")
            cursor.execute("PRAGMA busy_timeout=30000")  # Wait up to 30 seconds for locks
            cursor.close()
        
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False
        )
        
        self._initialized = False
    
    def initialize(self, seed_config: bool = True) -> None:
        """
        Initialize the database schema.
        Creates all tables if they don't exist.
        
        Args:
            seed_config: If True, seed default configuration values
        """
        Base.metadata.create_all(bind=self.engine)
        
        if seed_config:
            with self.get_session() as session:
                seed_default_config(session)
        
        self._initialized = True
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Get a database session using context manager.
        Automatically handles commit/rollback.
        
        Usage:
            with db.get_session() as session:
                session.add(position)
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def get_new_session(self) -> Session:
        """
        Get a new session without context manager.
        Caller is responsible for commit/rollback/close.
        """
        return self.SessionLocal()
    
    def backup(self, backup_dir: Optional[str] = None) -> str:
        """
        Create a backup of the database.
        
        Args:
            backup_dir: Directory for backup file. 
                       Defaults to 'backups' subdirectory.
        
        Returns:
            Path to the backup file
        """
        if self.db_path == ":memory:":
            raise ValueError("Cannot backup in-memory database")
        
        if backup_dir is None:
            backup_dir = os.path.join(
                os.path.dirname(self.db_path),
                'backups'
            )
        
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"canslim_monitor_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_name)
        
        # Use SQLite backup API for consistency
        with self.engine.connect() as conn:
            conn.execute(text(f"VACUUM INTO '{backup_path}'"))
        
        return backup_path
    
    def cleanup_backups(self, backup_dir: Optional[str] = None, keep: int = 7) -> int:
        """
        Remove old backup files, keeping the most recent ones.
        
        Args:
            backup_dir: Directory containing backups
            keep: Number of backups to retain
        
        Returns:
            Number of backups deleted
        """
        if backup_dir is None:
            backup_dir = os.path.join(
                os.path.dirname(self.db_path),
                'backups'
            )
        
        if not os.path.exists(backup_dir):
            return 0
        
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith('.db')],
            reverse=True
        )
        
        deleted = 0
        for backup in backups[keep:]:
            os.remove(os.path.join(backup_dir, backup))
            deleted += 1
        
        return deleted
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        stats = {}
        
        if self.db_path != ":memory:":
            stats['file_size_mb'] = os.path.getsize(self.db_path) / (1024 * 1024)
        
        with self.get_session() as session:
            # Count records in each table
            for table in ['positions', 'alerts', 'daily_snapshots', 'outcomes', 
                         'learned_weights', 'market_regime', 'config']:
                result = session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                stats[f'{table}_count'] = result.scalar()
            
            # Get active positions count
            result = session.execute(
                text("SELECT COUNT(*) FROM positions WHERE state >= 0")
            )
            stats['active_positions'] = result.scalar()
            
            # Get watching count
            result = session.execute(
                text("SELECT COUNT(*) FROM positions WHERE state = 0")
            )
            stats['watching_count'] = result.scalar()
        
        return stats
    
    def close(self) -> None:
        """Close all database connections."""
        self.engine.dispose()


# Singleton instance for application-wide use
_db_manager: Optional[DatabaseManager] = None


def get_database(
    db_path: Optional[str] = None,
    echo: bool = False,
    in_memory: bool = False,
    force_new: bool = False
) -> DatabaseManager:
    """
    Get the database manager singleton.
    
    Args:
        db_path: Path to database file
        echo: Log SQL statements
        in_memory: Use in-memory database
        force_new: Force creation of new instance
    
    Returns:
        DatabaseManager instance
    """
    global _db_manager
    
    if force_new or _db_manager is None:
        _db_manager = DatabaseManager(
            db_path=db_path,
            echo=echo,
            in_memory=in_memory
        )
    
    return _db_manager


def init_database(
    db_path: Optional[str] = None,
    echo: bool = False,
    seed_config: bool = True
) -> DatabaseManager:
    """
    Initialize the database (convenience function).
    
    Args:
        db_path: Path to database file
        echo: Log SQL statements
        seed_config: Seed default configuration
    
    Returns:
        Initialized DatabaseManager instance
    """
    db = get_database(db_path=db_path, echo=echo)
    db.initialize(seed_config=seed_config)
    return db
