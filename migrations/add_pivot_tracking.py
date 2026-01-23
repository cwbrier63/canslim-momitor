"""
Migration: Add Pivot Tracking Columns
=====================================
Adds columns for stale pivot tracking if they don't exist.

Run with:
    python -m canslim_monitor.migrations.add_pivot_tracking

Columns added to positions table:
    - pivot_set_date: Date when pivot was set/last changed
    - pivot_distance_pct: Current % distance from pivot
    - pivot_status: FRESH, AGING, STALE, EXTENDED
"""

import sqlite3
import sys
from pathlib import Path


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


def get_database_path() -> str:
    """
    Get database path following the application's config precedent.
    
    Priority:
    1. Config file database.path setting
    2. CANSLIM_DATA_DIR env variable + canslim_monitor.db
    3. Current directory + canslim_monitor.db
    """
    import os
    
    # Try to load from config (same pattern as application)
    try:
        from canslim_monitor.utils.config import load_config
        config = load_config()
        db_path = config.get('database', {}).get('path')
        if db_path:
            # If relative path, resolve from current directory
            path = Path(db_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            return str(path)
    except Exception as e:
        print(f"  Note: Could not load config ({e}), using defaults")
    
    # Fall back to environment variable or current directory
    data_dir = os.environ.get('CANSLIM_DATA_DIR', '.')
    return os.path.join(data_dir, 'canslim_monitor.db')


def run_migration(db_path: str = None):
    """Run the pivot tracking migration."""
    # Get database path from config if not provided
    if db_path is None:
        db_path = get_database_path()
    
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: Database not found: {db_path}")
        print(f"\nSearched path: {db_file.absolute()}")
        return False
    
    print(f"\n{'='*60}")
    print("MIGRATION: Add Pivot Tracking Columns")
    print(f"{'='*60}")
    print(f"Database: {db_file.absolute()}\n")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Add columns to positions table
        print("Checking positions table...")
        columns_added = 0
        
        if add_column_if_missing(cursor, 'positions', 'pivot_set_date', 'DATE'):
            columns_added += 1
        
        if add_column_if_missing(cursor, 'positions', 'pivot_distance_pct', 'REAL'):
            columns_added += 1
        
        if add_column_if_missing(cursor, 'positions', 'pivot_status', 'TEXT'):
            columns_added += 1
        
        conn.commit()
        conn.close()
        
        print(f"\n{'='*60}")
        if columns_added > 0:
            print(f"Migration complete! Added {columns_added} column(s).")
        else:
            print("Migration complete! No changes needed - all columns exist.")
        print(f"{'='*60}\n")
        
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
