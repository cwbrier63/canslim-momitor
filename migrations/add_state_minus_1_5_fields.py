"""
Migration: Add State -1.5 (WATCHING_EXITED) fields to positions table.

State -1.5 is used for re-entry monitoring of stopped-out positions.
When a position exits via stop loss or technical sell (not profit),
it transitions to State -1.5 for monitoring MA bounces and pivot retests.

New columns:
- original_pivot: Preserved pivot for retest detection
- ma_test_count: Track # of MA bounces (max 3)
- watching_exited_since: When entered State -1.5

Run: python -m canslim_monitor.migrations.add_state_minus_1_5_fields
"""

import sqlite3
from pathlib import Path
import sys


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Add State -1.5 related columns to positions table."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check which columns need to be added
    cursor.execute("PRAGMA table_info(positions)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    columns_to_add = [
        ("original_pivot", "REAL", None),
        ("ma_test_count", "INTEGER", "0"),
        ("watching_exited_since", "DATETIME", None),
    ]

    added = 0
    for col_name, col_type, default in columns_to_add:
        if col_name not in existing_columns:
            if default is not None:
                sql = f"ALTER TABLE positions ADD COLUMN {col_name} {col_type} DEFAULT {default}"
            else:
                sql = f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}"

            print(f"  Adding column: {col_name} ({col_type})")
            cursor.execute(sql)
            added += 1
        else:
            print(f"  Column already exists: {col_name}")

    conn.commit()
    conn.close()

    if added > 0:
        print(f"\nMigration complete: {added} columns added.")
    else:
        print("\nNo changes needed - all columns already exist.")


def verify_migration():
    """Verify the migration was successful."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(positions)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

    required = ["original_pivot", "ma_test_count", "watching_exited_since"]
    missing = [col for col in required if col not in columns]

    conn.close()

    if missing:
        print(f"VERIFICATION FAILED - Missing columns: {missing}")
        return False
    else:
        print("VERIFICATION PASSED - All State -1.5 columns present.")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - State -1.5 Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
