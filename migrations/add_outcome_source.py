"""
Migration: Add 'source' column to outcomes table.
Tracks where each outcome came from: live, swingtrader, manual, backtest.

Run: python migrations/add_outcome_source.py
"""

import sqlite3
import sys
from pathlib import Path


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Add source column to outcomes table."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if column exists
    cursor.execute("PRAGMA table_info(outcomes)")
    columns = {row[1] for row in cursor.fetchall()}

    if 'source' in columns:
        print("  Column 'source' already exists - skipping")
    else:
        print("  Adding column: source")
        cursor.execute("""
            ALTER TABLE outcomes
            ADD COLUMN source TEXT DEFAULT 'live'
        """)
        print("  Column added successfully")

    conn.commit()
    conn.close()

    print("\nMigration complete.")


def verify_migration():
    """Verify the migration was successful."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(outcomes)")
    columns = {row[1] for row in cursor.fetchall()}

    conn.close()

    if 'source' in columns:
        print("VERIFICATION PASSED - source column exists")
        return True
    else:
        print("VERIFICATION FAILED - source column not found")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - Add Outcome Source Column Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
