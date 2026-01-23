"""
Migration: Add Volume Tracking
==============================
Creates historical_bars table and adds avg_volume columns to positions.

Run with:
    python -m canslim_monitor.migrations.add_volume_tracking

Tables/Columns added:
    - historical_bars table (for storing daily OHLCV from Polygon)
    - positions.avg_volume_50d (calculated 50-day average volume)
    - positions.volume_updated_at (timestamp of last volume update)
"""

import sqlite3
import sys
from pathlib import Path


def get_existing_tables(cursor) -> set:
    """Get existing table names."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def get_existing_columns(cursor, table_name: str) -> set:
    """Get existing column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def add_column_if_missing(cursor, table: str, column: str, col_type: str) -> bool:
    """Add a column if it doesn't exist. Returns True if added."""
    existing = get_existing_columns(cursor, table)
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"  ✓ Added column: {table}.{column} ({col_type})")
        return True
    else:
        print(f"  - Column exists: {table}.{column}")
        return False


def run_migration(db_path: str = None):
    """Run the volume tracking migration."""
    # Default database path
    if db_path is None:
        db_path = "C:/Trading/canslim_positions.db"
    
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found: {db_path}")
        return False
    
    print(f"\n{'='*60}")
    print("MIGRATION: Add Volume Tracking")
    print(f"{'='*60}")
    print(f"Database: {db_path}\n")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        changes_made = 0
        
        # 1. Create historical_bars table if not exists
        print("Checking historical_bars table...")
        existing_tables = get_existing_tables(cursor)
        
        if 'historical_bars' not in existing_tables:
            cursor.execute("""
                CREATE TABLE historical_bars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    bar_date DATE NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    vwap REAL,
                    transactions INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, bar_date)
                )
            """)
            cursor.execute("CREATE INDEX idx_historical_bars_symbol ON historical_bars(symbol)")
            cursor.execute("CREATE INDEX idx_historical_bars_date ON historical_bars(bar_date)")
            cursor.execute("CREATE INDEX idx_historical_bars_symbol_date ON historical_bars(symbol, bar_date)")
            print("  ✓ Created table: historical_bars")
            changes_made += 1
        else:
            print("  - Table exists: historical_bars")
        
        # 2. Add columns to positions table
        print("\nChecking positions table...")
        
        if add_column_if_missing(cursor, 'positions', 'avg_volume_50d', 'INTEGER'):
            changes_made += 1
        
        if add_column_if_missing(cursor, 'positions', 'volume_updated_at', 'TIMESTAMP'):
            changes_made += 1
        
        conn.commit()
        conn.close()
        
        print(f"\n{'='*60}")
        if changes_made > 0:
            print(f"Migration complete! Made {changes_made} change(s).")
        else:
            print("Migration complete! No changes needed - all objects exist.")
        print(f"{'='*60}")
        
        # Print next steps
        print("\nNEXT STEPS:")
        print("1. Add your Polygon API key to user_config.yaml:")
        print("   polygon:")
        print("     api_key: \"your_api_key_here\"")
        print("")
        print("2. Run volume update for watchlist:")
        print("   python -m canslim_monitor.services.volume_service update")
        print("")
        
        return True
        
    except Exception as e:
        print(f"\nError during migration: {e}")
        return False


def main():
    """CLI entry point."""
    db_path = None
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    success = run_migration(db_path)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
