"""
Migration: Add prior_fund_count column to positions table.

This column stores the fund count from the prior quarter,
used to calculate funds_qtr_chg (fund_count - prior_fund_count).

Run: python migrations/add_prior_fund_count.py
"""

import sqlite3
from pathlib import Path
import sys


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Add prior_fund_count column to positions table."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(positions)")
    columns = {row[1] for row in cursor.fetchall()}

    if 'prior_fund_count' in columns:
        print("  Column 'prior_fund_count' already exists - skipping")
    else:
        print("  Adding column: prior_fund_count")
        cursor.execute("""
            ALTER TABLE positions
            ADD COLUMN prior_fund_count INTEGER
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

    cursor.execute("PRAGMA table_info(positions)")
    columns = {row[1] for row in cursor.fetchall()}

    conn.close()

    if 'prior_fund_count' in columns:
        print("VERIFICATION PASSED - prior_fund_count column exists")
        return True
    else:
        print("VERIFICATION FAILED - prior_fund_count column not found")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - Add prior_fund_count Column Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
