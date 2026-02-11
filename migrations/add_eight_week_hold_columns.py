"""
Migration: Add 8-week hold columns to positions table

Adds columns to persist 8-week hold rule state so it survives service restarts
and correctly suppresses TP1 alerts during the hold period.

Columns:
- eight_week_hold_active: Boolean flag for active hold
- eight_week_hold_start: Date when the hold was activated
- eight_week_hold_end: Date when the 8-week hold expires
- eight_week_power_move_pct: The gain % that triggered the rule
- eight_week_power_move_weeks: How many weeks after breakout it triggered

Usage:
    python -m migrations.add_eight_week_hold_columns --db "C:/Trading/canslim_monitor/canslim_positions.db"
"""

import argparse
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path


def check_column_exists(cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def add_eight_week_hold_columns(db_path: str, backup: bool = True):
    """Add 8-week hold columns to positions table."""

    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return False

    # Create backup
    if backup:
        backup_path = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        print(f"Creating backup: {backup_path}")
        shutil.copy(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    table = 'positions'

    # Verify table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if not cursor.fetchone():
        print(f"ERROR: Table '{table}' does not exist.")
        conn.close()
        return False

    columns_to_add = [
        ('eight_week_hold_active', 'BOOLEAN DEFAULT 0'),
        ('eight_week_hold_start', 'DATE DEFAULT NULL'),
        ('eight_week_hold_end', 'DATE DEFAULT NULL'),
        ('eight_week_power_move_pct', 'REAL DEFAULT NULL'),
        ('eight_week_power_move_weeks', 'REAL DEFAULT NULL'),
    ]

    try:
        added = 0
        for column_name, column_type in columns_to_add:
            if check_column_exists(cursor, table, column_name):
                print(f"Column '{column_name}' already exists. Skipping.")
            else:
                print(f"Adding '{column_name}' column to {table}...")
                cursor.execute(f"""
                    ALTER TABLE {table}
                    ADD COLUMN {column_name} {column_type}
                """)
                added += 1
                print(f"  -> Added '{column_name}'")

        conn.commit()

        if added > 0:
            print(f"\nSUCCESS: {added} column(s) added successfully.")
        else:
            print("\nNo columns needed to be added.")

        # Verify all columns exist
        print("\nVerifying columns...")
        all_exist = True
        for column_name, _ in columns_to_add:
            exists = check_column_exists(cursor, table, column_name)
            status = "OK" if exists else "MISSING"
            print(f"  [{status}] {column_name}")
            if not exists:
                all_exist = False

        return all_exist

    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Add 8-week hold columns to positions table")
    parser.add_argument('--db', required=True, help="Path to SQLite database")
    parser.add_argument('--no-backup', action='store_true', help="Skip backup creation")

    args = parser.parse_args()

    success = add_eight_week_hold_columns(args.db, backup=not args.no_backup)

    if success:
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)
        print("""
New columns added to positions:
- eight_week_hold_active: Whether 8-week hold rule is active (Boolean)
- eight_week_hold_start: Date the hold was activated
- eight_week_hold_end: Date the 8-week hold expires
- eight_week_power_move_pct: Gain % that triggered the rule
- eight_week_power_move_weeks: Weeks after breakout when triggered
""")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
