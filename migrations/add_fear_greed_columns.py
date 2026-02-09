"""
Migration: Add CNN Fear & Greed Index columns to market_regime_alerts table

Run this script to add fear_greed_score, fear_greed_rating, fear_greed_previous,
and fear_greed_timestamp columns.

Usage:
    python -m migrations.add_fear_greed_columns --db "C:/Trading/canslim_monitor/canslim_positions.db"
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


def add_fear_greed_columns(db_path: str, backup: bool = True):
    """Add CNN Fear & Greed columns to market_regime_alerts table."""

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

    table = 'market_regime_alerts'

    # Verify table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if not cursor.fetchone():
        print(f"ERROR: Table '{table}' does not exist. Run regime table creation first.")
        conn.close()
        return False

    columns_to_add = [
        ('fear_greed_score', 'REAL DEFAULT NULL'),
        ('fear_greed_rating', 'VARCHAR(20) DEFAULT NULL'),
        ('fear_greed_previous', 'REAL DEFAULT NULL'),
        ('fear_greed_timestamp', 'DATETIME DEFAULT NULL'),
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
    parser = argparse.ArgumentParser(description="Add CNN Fear & Greed columns to market_regime_alerts")
    parser.add_argument('--db', required=True, help="Path to SQLite database")
    parser.add_argument('--no-backup', action='store_true', help="Skip backup creation")

    args = parser.parse_args()

    success = add_fear_greed_columns(args.db, backup=not args.no_backup)

    if success:
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)
        print("""
New columns added to market_regime_alerts:
- fear_greed_score: CNN Fear & Greed Index value (0-100)
- fear_greed_rating: Rating text (Extreme Fear/Fear/Neutral/Greed/Extreme Greed)
- fear_greed_previous: Previous close score for trend comparison
- fear_greed_timestamp: When the F&G data was fetched
""")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
