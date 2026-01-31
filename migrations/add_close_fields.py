"""
Migration: Add close-related columns to positions table

Run this script to add close_price, close_date, close_reason, and realized_pnl_pct columns.

Usage:
    python -m migrations.add_close_fields --db "C:/Trading/canslim_monitor/canslim_positions.db"
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


def add_close_fields(db_path: str, backup: bool = True):
    """Add close-related columns to positions table."""

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

    # Columns to add with their SQL types
    columns_to_add = [
        ('close_price', 'REAL DEFAULT NULL'),
        ('close_date', 'DATE DEFAULT NULL'),
        ('close_reason', 'VARCHAR(30) DEFAULT NULL'),
        ('realized_pnl', 'REAL DEFAULT NULL'),
        ('realized_pnl_pct', 'REAL DEFAULT NULL'),
    ]

    try:
        added = 0
        for column_name, column_type in columns_to_add:
            if check_column_exists(cursor, 'positions', column_name):
                print(f"Column '{column_name}' already exists. Skipping.")
            else:
                print(f"Adding '{column_name}' column to positions table...")
                cursor.execute(f"""
                    ALTER TABLE positions
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
            exists = check_column_exists(cursor, 'positions', column_name)
            status = "✓" if exists else "✗"
            print(f"  {status} {column_name}")
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
    parser = argparse.ArgumentParser(description="Add close fields to positions table")
    parser.add_argument('--db', required=True, help="Path to SQLite database")
    parser.add_argument('--no-backup', action='store_true', help="Skip backup creation")

    args = parser.parse_args()

    success = add_close_fields(args.db, backup=not args.no_backup)

    if success:
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)
        print("""
New columns added to positions table:
- close_price: Exit price when position is fully closed
- close_date: Date when position was closed
- close_reason: Reason for close (STOP_HIT, TP_HIT, MANUAL, etc.)
- realized_pnl: Dollar P&L for closed positions
- realized_pnl_pct: Percentage P&L for closed positions

These fields can now be edited via the Edit Position dialog for
closed positions (state -1 or -2).
""")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
