"""
Database Migration: Add IBD Exposure and Entry Risk Tables/Columns

Run this script to update existing database with:
1. New columns on market_regime_alerts table
2. New ibd_exposure_history table
3. New ibd_exposure_current table

Usage:
    python migrations/migrate_ibd_exposure.py
"""

import sys
import logging
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text, inspect
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_database_path():
    """Get path to the SQLite database."""
    # Try common locations
    possible_paths = [
        Path.home() / 'canslim_monitor' / 'canslim_positions.db',
        Path(__file__).parent.parent / 'canslim_positions.db',
        Path('C:/Trading/canslim_monitor/canslim_positions.db'),
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    
    # Default to first path
    return str(possible_paths[0])


def run_migration(engine):
    """Run the migration to add IBD exposure tables and columns."""
    
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    with engine.begin() as conn:
        
        # 1. Add new columns to market_regime_alerts if they don't exist
        logger.info("Checking market_regime_alerts table...")
        
        if 'market_regime_alerts' in existing_tables:
            existing_columns = [c['name'] for c in inspector.get_columns('market_regime_alerts')]
            
            new_columns = [
                ("ibd_market_status", "VARCHAR(30)"),
                ("ibd_exposure_min", "INTEGER"),
                ("ibd_exposure_max", "INTEGER"),
                ("ibd_exposure_updated_at", "DATETIME"),
                ("entry_risk_level", "VARCHAR(20)"),
                ("entry_risk_score", "FLOAT"),
            ]
            
            for col_name, col_type in new_columns:
                if col_name not in existing_columns:
                    logger.info(f"  Adding column: {col_name}")
                    conn.execute(text(f"ALTER TABLE market_regime_alerts ADD COLUMN {col_name} {col_type}"))
                else:
                    logger.info(f"  Column already exists: {col_name}")
        
        # 2. Create ibd_exposure_history table
        logger.info("Creating ibd_exposure_history table...")
        
        if 'ibd_exposure_history' not in existing_tables:
            conn.execute(text("""
                CREATE TABLE ibd_exposure_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    effective_date DATE NOT NULL,
                    market_status VARCHAR(30) NOT NULL,
                    exposure_min INTEGER NOT NULL,
                    exposure_max INTEGER NOT NULL,
                    distribution_days_spy INTEGER,
                    distribution_days_qqq INTEGER,
                    notes VARCHAR(500),
                    source VARCHAR(50) DEFAULT 'MarketSurge',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX ix_ibd_exposure_effective ON ibd_exposure_history(effective_date)"))
            logger.info("  Created ibd_exposure_history table")
        else:
            logger.info("  ibd_exposure_history table already exists")
        
        # 3. Create ibd_exposure_current table (singleton)
        logger.info("Creating ibd_exposure_current table...")
        
        if 'ibd_exposure_current' not in existing_tables:
            conn.execute(text("""
                CREATE TABLE ibd_exposure_current (
                    id INTEGER PRIMARY KEY,
                    market_status VARCHAR(30) NOT NULL DEFAULT 'CONFIRMED_UPTREND',
                    exposure_min INTEGER NOT NULL DEFAULT 80,
                    exposure_max INTEGER NOT NULL DEFAULT 100,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_by VARCHAR(50) DEFAULT 'user',
                    notes VARCHAR(500)
                )
            """))
            
            # Insert default row
            conn.execute(text("""
                INSERT INTO ibd_exposure_current (id, market_status, exposure_min, exposure_max, updated_by)
                VALUES (1, 'CONFIRMED_UPTREND', 80, 100, 'migration')
            """))
            logger.info("  Created ibd_exposure_current table with default values")
        else:
            logger.info("  ibd_exposure_current table already exists")
        
        logger.info("Migration completed successfully!")


def verify_migration(engine):
    """Verify the migration was successful."""
    inspector = inspect(engine)
    
    logger.info("\nVerifying migration...")
    
    # Check tables exist
    tables = inspector.get_table_names()
    required_tables = ['market_regime_alerts', 'ibd_exposure_history', 'ibd_exposure_current']
    
    for table in required_tables:
        if table in tables:
            logger.info(f"  ✓ Table exists: {table}")
        else:
            logger.error(f"  ✗ Table missing: {table}")
            return False
    
    # Check columns on market_regime_alerts
    columns = [c['name'] for c in inspector.get_columns('market_regime_alerts')]
    required_columns = ['ibd_market_status', 'ibd_exposure_min', 'ibd_exposure_max', 
                       'ibd_exposure_updated_at', 'entry_risk_level', 'entry_risk_score']
    
    for col in required_columns:
        if col in columns:
            logger.info(f"  ✓ Column exists: market_regime_alerts.{col}")
        else:
            logger.error(f"  ✗ Column missing: market_regime_alerts.{col}")
            return False
    
    # Check ibd_exposure_current has default row
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ibd_exposure_current WHERE id = 1"))
        row = result.fetchone()
        if row:
            logger.info(f"  ✓ Default IBD exposure: {row[1]} {row[2]}-{row[3]}%")
        else:
            logger.error("  ✗ No default row in ibd_exposure_current")
            return False
    
    logger.info("\nAll verifications passed!")
    return True


def main():
    """Main entry point."""
    db_path = get_database_path()
    logger.info(f"Database path: {db_path}")
    
    if not Path(db_path).exists():
        logger.error(f"Database not found at {db_path}")
        logger.info("Run the main application first to create the database.")
        return 1
    
    engine = create_engine(f'sqlite:///{db_path}')
    
    try:
        run_migration(engine)
        if verify_migration(engine):
            return 0
        else:
            return 1
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
